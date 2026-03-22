"""
Product Detail Agent - Answers user questions about a specific shown product.

Handles post-recommendation questions like:
  - "Tell me more about the collagen one"
  - "Is that vegan?"
  - "How should I take it?"
  - "What are the ingredients in the sleep one?"

Triggered organically when the Router or Refinement agent detects the user
is asking about a specific product already shown in recommendations.

Preserves current session status (like ingredient_info) so the next turn
routes correctly back to the interview or refinement flow.
"""

import uuid
import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.agents.llm import get_bedrock_llm
from app.agents.validators import parse_list, parse_bool
from app.db.repositories.product import ProductRepository
from app.knowledge.graph_loader import get_knowledge_graph, list_available_graphs

logger = logging.getLogger(__name__)

MAX_PDA_HISTORY = 10


class ProductDetailResponse(BaseModel):
    """Structured response from the Product Detail agent."""
    answer: str = Field(
        description=(
            "A focused 100-200 word answer to the user's question about this product. "
            "Use markdown for readability. Be warm, confident, and informative. "
            "Never make unsubstantiated medical claims."
        )
    )
    disclaimers: list[str] = Field(
        default_factory=list,
        description="Safety disclaimers if the answer touches on health/medical topics. Keep short."
    )
    contains_medical_claims: bool = Field(
        default=False,
        description="True if the answer references health benefits, mechanisms, or medical effects."
    )
    suggested_followups: list[str] = Field(
        default_factory=list,
        description="3-4 natural follow-up questions the user might ask about this product."
    )

    @field_validator("disclaimers", mode="before")
    @classmethod
    def parse_disclaimers(cls, v: Any) -> list:
        return parse_list(v)

    @field_validator("suggested_followups", mode="before")
    @classmethod
    def parse_suggested_followups(cls, v: Any) -> list:
        return parse_list(v)

    @field_validator("contains_medical_claims", mode="before")
    @classmethod
    def parse_medical_claims(cls, v: Any) -> bool:
        return parse_bool(v)


class ProductMatchResponse(BaseModel):
    """LLM response for matching a user's reference to a shown product."""
    matched_index: int = Field(
        description=(
            "The 1-based index of the product the user is asking about. "
            "Set to 0 if no product matches or the reference is too ambiguous."
        )
    )
    confidence: str = Field(
        description=(
            "How confident you are in the match: "
            "'high' if the user clearly refers to this product, "
            "'low' if it's a reasonable guess but ambiguous, "
            "'none' if you cannot determine which product they mean."
        )
    )
    reasoning: str = Field(default="", description="Brief explanation for the match.")


async def _match_product_with_llm(
    user_message: str,
    product_reference: str,
    products: list[dict],
) -> tuple[dict | None, str]:
    """
    Use a single LLM call to match the user's reference to a shown product.

    Args:
        user_message: The full user message.
        product_reference: The extracted product reference phrase.
        products: Shown products (capped to top 5).

    Returns:
        (matched_product_dict_or_None, confidence: "high"|"low"|"none")
    """
    if not products or not product_reference:
        return None, "none"

    # Cap to 5 products for a tight prompt
    candidates = products[:5]

    product_list = "\n".join(
        f"{i + 1}. {p.get('name', 'Unknown')}"
        + (f" — {p.get('brand', '')}" if p.get("brand") else "")
        + (f" ({p.get('description', '')[:80]})" if p.get("description") else "")
        for i, p in enumerate(candidates)
    )

    prompt = f"""The user said: "{user_message}"
The extracted product reference is: "{product_reference}"

Here are the products currently shown to the user:
{product_list}

Which product (by number) is the user asking about?

Rules:
- If the user clearly names or describes one product, return its number with confidence "high".
- If the user uses a vague reference like "it", "that one", "the first one", or a partial keyword that could match one product, return your best guess with confidence "low".
- If you truly cannot determine which product, set matched_index to 0 and confidence to "none".
- Prefer matching over not matching — users usually refer to a product they've just seen."""

    model = get_bedrock_llm(structured_output_schema=ProductMatchResponse)

    try:
        result: ProductMatchResponse = await model.ainvoke(prompt)
    except Exception as e:
        logger.warning(f"Product match LLM call failed: {e}. Falling back to no match.")
        return None, "none"

    confidence = result.confidence.lower().strip()
    idx = result.matched_index

    if idx < 1 or idx > len(candidates) or confidence == "none":
        return None, "none"

    logger.info(
        f"Product match LLM: index={idx}, confidence={confidence}, "
        f"reasoning='{result.reasoning}', matched='{candidates[idx - 1].get('name')}'"
    )
    return candidates[idx - 1], confidence


def _enrich_product_with_graph(product: dict) -> str:
    """
    Look up product ingredients in knowledge graphs and return
    a formatted intelligence block for the LLM prompt.
    """
    attributes = product.get("attributes") or {}
    ingredients_raw = attributes.get("key_ingredients") or attributes.get("ingredients") or []

    if isinstance(ingredients_raw, str):
        ingredients_raw = [i.strip() for i in ingredients_raw.split(",")]

    if not ingredients_raw:
        return ""

    lines = ["**Ingredient Intelligence (from knowledge graph):**"]
    found_any = False

    for ing_name in ingredients_raw[:8]:  # cap at 8 ingredients
        ing_lower = ing_name.lower().strip()

        for graph_name in list_available_graphs():
            try:
                graph = get_knowledge_graph(graph_name)
                ingredients = graph.find_nodes_by_type("ingredient")

                for node in ingredients:
                    node_name = node.get("name", "").lower()
                    node_display = node.get("display_name", "").lower()

                    if ing_lower in node_name or ing_lower in node_display:
                        display = node.get("display_name") or node.get("name", ing_name)
                        function = node.get("function", "")
                        category = node.get("category", "")

                        parts = [f"- **{display}**"]
                        if category:
                            parts[0] += f" ({category})"
                        if function:
                            parts.append(f"  Mechanism: {function.replace('_', ' ')}")

                        # Check for contraindications or warnings
                        contraindications = node.get("contraindications", [])
                        if contraindications:
                            parts.append(f"  Contraindications: {', '.join(contraindications[:3])}")

                        lines.append("\n".join(parts))
                        found_any = True
                        break
                if found_any and lines[-1].startswith("- **"):
                    break  # found this ingredient, move to next
            except Exception as e:
                logger.warning(f"Error searching graph '{graph_name}' for ingredient '{ing_name}': {e}")

    return "\n".join(lines) if found_any else ""


def _format_product_for_prompt(product: dict) -> str:
    """Format full product data as a prompt block."""
    parts = [f"**Product: {product.get('name', 'Unknown')}**"]

    if product.get("brand"):
        parts.append(f"Brand: {product['brand']}")
    if product.get("price") is not None:
        parts.append(f"Price: {product.get('currency', 'USD')} {product['price']}")
    if product.get("description"):
        parts.append(f"Description: {product['description']}")

    attributes = product.get("attributes") or {}
    if attributes:
        attr_lines = []
        for key, val in attributes.items():
            if key.startswith("_"):
                continue
            display_key = key.replace("_", " ").title()
            if isinstance(val, list):
                attr_lines.append(f"  {display_key}: {', '.join(str(v) for v in val)}")
            elif isinstance(val, bool):
                attr_lines.append(f"  {display_key}: {'Yes' if val else 'No'}")
            else:
                attr_lines.append(f"  {display_key}: {val}")
        if attr_lines:
            parts.append("Attributes:\n" + "\n".join(attr_lines))

    return "\n".join(parts)


def _product_to_context_dict(product_data: dict) -> dict:
    """Build the product_context dict for the frontend."""
    return {
        "id": product_data.get("id"),
        "name": product_data.get("name"),
        "brand": product_data.get("brand"),
        "price": product_data.get("price"),
        "currency": product_data.get("currency", "USD"),
        "product_url": product_data.get("product_url"),
        "image_url": product_data.get("image_url"),
        "description": product_data.get("description"),
        "attributes": product_data.get("attributes") or {},
    }


async def product_detail_agent(state: AgentState, db: AsyncSession) -> AgentState:
    """
    Answers user questions about a specific product from the shown recommendations.

    State changes:
      - Sets response with the product-specific answer.
      - Sets product_context with full product data for frontend rendering.
      - Sets suggested_replies with follow-up questions.
      - Preserves original status so the next turn routes correctly.
    """
    new_state = state.copy()

    user_message = state.get("user_message", "")
    current_status = state.get("status", "completed")
    extracted_context = state.get("extracted_context", {})

    # 0. Handle pending confirmation from a previous low-confidence match
    pending_confirm = extracted_context.get("pda_pending_confirm")
    if pending_confirm:
        # User was asked "are you asking about X?" — check their answer
        affirm = user_message.lower().strip()
        is_yes = affirm.startswith("yes") or pending_confirm.lower() in affirm

        # Clean up pending state regardless
        updated_context = {**extracted_context}
        updated_context.pop("pda_pending_confirm", None)
        original_question = updated_context.pop("pda_pending_question", user_message)
        new_state["extracted_context"] = updated_context
        extracted_context = updated_context

        if is_yes:
            # User confirmed — set reference to the confirmed product name
            extracted_context["pda_product_reference"] = pending_confirm
            new_state["extracted_context"] = extracted_context
            # Override user_message to the original question for the answer
            user_message = original_question
        else:
            # User said no — show selection list
            shown = extracted_context.get("shown_products") or []
            product_names = [p.get("name", "") for p in shown[:5] if p.get("name")]
            if product_names:
                numbered = "\n".join(f"{i + 1}. **{n}**" for i, n in enumerate(product_names))
                new_state["response"] = (
                    "No problem! Which of these products would you like to know about?\n\n"
                    f"{numbered}"
                )
                new_state["suggested_replies"] = product_names[:4]
            else:
                new_state["response"] = "Could you tell me the product name you're interested in?"
                new_state["suggested_replies"] = []
            new_state["next_agent"] = None
            new_state["product_context"] = None
            return new_state

    # 1. Get the product reference from extracted_context
    product_reference = extracted_context.get("pda_product_reference", "")

    # Multi-turn continuity: if no explicit product reference but we have a
    # last-discussed product, assume the user is asking about the same one.
    last_product = extracted_context.get("pda_last_product")
    if not product_reference and last_product:
        product_reference = last_product
        logger.info(f"PDA multi-turn: using last product '{last_product}' as reference")

    # 2. Match against shown products using LLM
    # Read from extracted_context["shown_products"] (persisted across turns)
    # since initial_products/final_products start empty each turn.
    available_products = extracted_context.get("shown_products") or []
    matched, confidence = await _match_product_with_llm(
        user_message, product_reference, available_products
    )

    if not matched or confidence == "none":
        # No match — ask user to select from the list
        product_names = [p.get("name", "") for p in available_products if p.get("name")][:5]
        if product_names:
            numbered = "\n".join(f"{i + 1}. **{n}**" for i, n in enumerate(product_names))
            new_state["response"] = (
                "I'd love to help! Which product would you like to know more about?\n\n"
                f"{numbered}"
            )
            new_state["suggested_replies"] = product_names[:4]
        else:
            new_state["response"] = (
                "I'm not sure which product you're referring to. "
                "Could you tell me the product name?"
            )
            new_state["suggested_replies"] = []
        new_state["next_agent"] = None
        new_state["product_context"] = None
        return new_state

    if confidence == "low":
        # Low-confidence match — confirm with user before proceeding
        product_name = matched.get("name", "this product")
        new_state["response"] = (
            f"Just to make sure — are you asking about **{product_name}**?"
        )
        # Store the tentative match so if user confirms, we can use it next turn
        updated_context = {**extracted_context}
        updated_context["pda_pending_confirm"] = matched.get("name", "")
        updated_context["pda_pending_question"] = user_message
        updated_context.pop("pda_product_reference", None)
        new_state["extracted_context"] = updated_context
        new_state["suggested_replies"] = [
            f"Yes, {product_name}",
            "No, a different one",
        ]
        new_state["next_agent"] = None
        new_state["product_context"] = None
        return new_state

    # 3. Load fresh product data from DB
    product_data = dict(matched)  # start with state data
    try:
        product_id = uuid.UUID(str(matched["id"]))
        repo = ProductRepository(db)
        db_product = await repo.get_by_id(product_id)
        if db_product:
            product_data = {
                "id": str(db_product.id),
                "name": db_product.name,
                "brand": db_product.brand,
                "price": float(db_product.price) if db_product.price else None,
                "currency": db_product.currency,
                "product_url": db_product.product_url,
                "image_url": db_product.image_url,
                "description": db_product.description,
                "attributes": db_product.attributes if hasattr(db_product, "attributes") else {},
            }
    except Exception as e:
        logger.warning(f"Could not load fresh product from DB: {e}. Using state data.")

    # 4. Enrich with knowledge graph
    kg_context = _enrich_product_with_graph(product_data)

    # 5. Load PDA conversation history
    pda_history = extracted_context.get("pda_history", [])

    # 6. Build prompt
    product_block = _format_product_for_prompt(product_data)

    history_block = ""
    if pda_history:
        history_lines = []
        for entry in pda_history[-MAX_PDA_HISTORY:]:
            history_lines.append(f"User: {entry.get('user', '')}")
            history_lines.append(f"Assistant: {entry.get('assistant', '')}")
        history_block = "**Previous questions about this product:**\n" + "\n".join(history_lines)

    system_prompt = f"""You are a knowledgeable product specialist for CurateAI. The user is asking about a specific product from their recommendations. Your job is to answer their question thoroughly and build purchase confidence.

{product_block}

{kg_context}

{history_block}

**Rules:**
- Answer the user's specific question in 100-200 words using markdown.
- Be warm, confident, and informative — like a knowledgeable friend.
- Ground your answer in the product's actual attributes and ingredients.
- If knowledge graph data is available, use it to explain mechanisms and benefits.
- NEVER make unsubstantiated medical claims. Use hedging language: "may help", "is commonly used for", "research suggests".
- If the product has safety-relevant attributes (allergens, pregnancy warnings), mention them when relevant.
- Include 3-4 natural follow-up questions the user might want to ask about THIS product.
- Add disclaimers if your answer touches on health benefits or medical topics."""

    user_prompt = f'The user asks: "{user_message}"'

    # 7. Invoke LLM
    model = get_bedrock_llm(structured_output_schema=ProductDetailResponse)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    try:
        result: ProductDetailResponse = await model.ainvoke(messages)
    except Exception as e:
        logger.error(f"Product detail agent LLM call failed: {e}")
        new_state["response"] = (
            f"I'd love to tell you more about **{product_data.get('name', 'this product')}**, "
            f"but I had trouble generating a response. Could you try asking again?"
        )
        new_state["suggested_replies"] = []
        new_state["product_context"] = _product_to_context_dict(product_data)
        new_state["next_agent"] = None
        return new_state

    # 8. Assemble response
    response_parts = [result.answer]
    if result.disclaimers:
        disclaimer_text = " | ".join(result.disclaimers)
        response_parts.append(f"\n*{disclaimer_text}*")

    new_state["response"] = "\n\n".join(response_parts)

    # 9. Update PDA history
    updated_history = list(pda_history)
    updated_history.append({
        "user": user_message,
        "assistant": result.answer[:500],  # cap stored response length
    })
    if len(updated_history) > MAX_PDA_HISTORY:
        updated_history = updated_history[-MAX_PDA_HISTORY:]

    updated_context = {**extracted_context}
    updated_context["pda_history"] = updated_history
    # Store last-discussed product for multi-turn continuity
    updated_context["pda_last_product"] = product_data.get("name", "")
    # Clean up the reference — it's been consumed
    updated_context.pop("pda_product_reference", None)
    new_state["extracted_context"] = updated_context

    # 10. Set product_context for frontend
    new_state["product_context"] = _product_to_context_dict(product_data)

    # 11. Suggested replies from LLM
    new_state["suggested_replies"] = result.suggested_followups[:4] if result.suggested_followups else []

    # 12. Preserve original status (like ingredient_info)
    # Don't change status — next turn routes correctly
    new_state["next_agent"] = None

    logger.info(
        f"Product detail agent: product='{product_data.get('name')}', "
        f"has_kg={bool(kg_context)}, history_len={len(updated_history)}, "
        f"preserved_status='{current_status}'"
    )

    return new_state
