"""
Ingredient Info Agent - Answers educational questions about ingredients and supplements.

Handles mid-conversation questions like:
  - "How does collagen work?"
  - "Why should I use vitamin C?"
  - "What does magnesium do?"
  - "Tell me about hyaluronic acid"
  - "Benefits of zinc"

Preserves current session state so the consultation continues after the question
is answered. If the user was mid-interview (awaiting_slot), the pending question
is re-surfaced at the end of the response.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import logging

from app.agents.state import AgentState
from app.agents.llm import get_bedrock_llm
from app.knowledge.graph_loader import get_knowledge_graph, list_available_graphs

logger = logging.getLogger(__name__)


class IngredientInfoResponse(BaseModel):
    """Structured extraction from the Ingredient Info agent."""
    ingredient_name: str = Field(
        description="The canonical common name of the ingredient/supplement being asked about (e.g., 'collagen', 'vitamin C', 'magnesium')"
    )
    explanation: str = Field(
        description=(
            "A focused, calm 3-4 sentence answer to the user's question. "
            "Ground it in their specific concern and what they've already shared (e.g., skin type, age, problem). "
            "Mention the key mechanism and why it's relevant to them. "
            "Warm, reassuring tone. No jargon, no product names, no dosages."
        )
    )


def _find_ingredients_in_graphs(query: str) -> List[Dict[str, Any]]:
    """
    Fuzzy-search all knowledge graphs for ingredients matching the query.

    Returns a list of matching ingredient node dicts (with 'domain' key added).
    Multiple matches are returned when the query is a category (e.g., "collagen"
    matches marine collagen, bovine collagen, and vegan collagen builder).
    """
    query_lower = query.lower().strip()
    found = []
    seen_ids: set = set()

    for graph_name in list_available_graphs():
        try:
            graph = get_knowledge_graph(graph_name)
            ingredients = graph.find_nodes_by_type("ingredient")

            for ing in ingredients:
                ing_id = ing.get("id", "")
                if ing_id in seen_ids:
                    continue

                ing_name = ing.get("name", "").lower()
                ing_display = ing.get("display_name", "").lower()

                if query_lower in ing_name or query_lower in ing_display:
                    found.append({**ing, "domain": graph_name})
                    seen_ids.add(ing_id)

        except Exception as e:
            logger.warning(f"Error searching graph '{graph_name}' for ingredient: {e}")

    return found


def _build_kg_context(ingredients: List[Dict[str, Any]]) -> str:
    """Build a concise knowledge-graph context string for the LLM prompt."""
    if not ingredients:
        return ""

    lines = ["Knowledge graph context:"]
    for ing in ingredients[:4]:  # cap at 4 to keep prompt tight
        display = ing.get("display_name") or ing.get("name", "Unknown")
        function = ing.get("function", "")
        category = ing.get("category", "")
        domain = ing.get("domain", "")

        parts = [f"- {display}"]
        if category:
            parts[0] += f" ({category})"
        if function:
            parts.append(f"  function: {function.replace('_', ' ')}")
        if domain:
            parts.append(f"  domain: {domain.replace('_', ' ')}")

        lines.append("\n".join(parts))

    return "\n".join(lines)


def _build_user_context(state: AgentState) -> str:
    """Build a brief summary of what we know about the user from the current session."""
    parts = []

    domain_slug = state.get("domain_slug")
    if domain_slug:
        parts.append(f"Current domain: {domain_slug.replace('_', ' ')}")

    graph_state = (state.get("extracted_context") or {}).get("graph_state", {})
    problem = graph_state.get("identified_problem")
    if problem:
        parts.append(f"User's concern: {problem.replace('_', ' ')}")

    filled = graph_state.get("filled_attributes", {})
    if filled:
        attrs = []
        for key, val in filled.items():
            raw = val.get("value") if isinstance(val, dict) else val
            if raw:
                attrs.append(f"{key.replace('_', ' ')}: {raw}")
        if attrs:
            parts.append("Known about user: " + ", ".join(attrs))

    return "\n".join(parts) if parts else ""


def _find_products_with_ingredient(ingredient_name: str, products: List[dict]) -> List[str]:
    """Return names of products in the current list that mention the ingredient."""
    query = ingredient_name.lower()
    matches = []

    for product in products:
        name = product.get("name", "").lower()
        description = product.get("description", "").lower()

        if query in name or query in description:
            matches.append(product.get("name", ""))

    return [p for p in matches if p][:3]


async def ingredient_info_agent(state: AgentState) -> AgentState:
    """
    Answers educational ingredient/supplement questions without disrupting the consultation flow.

    State changes:
      - Sets response with the ingredient explanation.
      - If status was 'awaiting_slot', appends the pending question so the user
        knows they still need to answer it.
      - All other state fields (status, domain_slug, extracted_context, etc.)
        are left unchanged.
    """
    new_state = state.copy()

    user_message = state.get("user_message", "")
    current_status = state.get("status", "active")

    available_products = state.get("final_products") or state.get("initial_products") or []

    # --- Build product context ---
    product_names = [p.get("name", "") for p in available_products[:6] if p.get("name")]
    product_context = (
        f"Products currently shown to the user: {', '.join(product_names)}"
        if product_names
        else ""
    )

    # --- Rough ingredient extraction for knowledge graph lookup ---
    # We do a quick scan with the raw user message to pre-fetch graph context.
    # The LLM will determine the canonical ingredient name properly.
    rough_ingredients = _find_ingredients_in_graphs(user_message)
    kg_context = _build_kg_context(rough_ingredients)

    # --- Build user session context ---
    user_context = _build_user_context(state)

    # --- Single LLM call: extract ingredient + generate explanation ---
    model = get_bedrock_llm(structured_output_schema=IngredientInfoResponse)

    context_block = "\n\n".join(filter(None, [user_context, kg_context, product_context]))

    prompt = f"""The user asked: "{user_message}"

{context_block}

Answer their question about the ingredient in 3-4 calm, clear sentences.
- Tie the explanation to their specific concern and what you already know about them (if anything).
- Focus on the most relevant mechanism or benefit for their situation.
- Keep the tone warm and reassuring — no jargon, no product names, no dosages.
- IMPORTANT: Respond in the same language as the user's message. If the user writes in Hindi, respond in Hindi. If in English, respond in English."""

    try:
        result: IngredientInfoResponse = await model.ainvoke(prompt)
    except Exception as e:
        logger.error(f"Ingredient info agent LLM call failed: {e}")
        new_state["response"] = (
            "I'd love to explain that! Unfortunately I had trouble looking that up right now. "
            "Could you try rephrasing or ask me again?"
        )
        new_state["suggested_replies"] = []
        return new_state

    # --- Find products in the current list that contain the ingredient ---
    matching_products = _find_products_with_ingredient(result.ingredient_name, available_products)

    # --- Assemble response ---
    response_parts = [result.explanation]

    if matching_products:
        if len(matching_products) == 1:
            response_parts.append(
                f"*{matching_products[0]}* in your recommendation list contains {result.ingredient_name}."
            )
        else:
            listed = ", ".join(f"*{p}*" for p in matching_products)
            response_parts.append(
                f"{listed} in your recommendation list contain {result.ingredient_name}."
            )

    new_state["response"] = "\n\n".join(response_parts)

    # Suggested replies: guide the user back to the consultation flow
    if current_status == "awaiting_slot":
        pending_slot_q = (state.get("extracted_context") or {}).get("pending_slot_question")
        if pending_slot_q and "personalise" not in pending_slot_q.lower():
            # Mid-interview: user was answering a slot question
            new_state["suggested_replies"] = ["Continue with questions", f"Tell me more about {result.ingredient_name}"]
        else:
            # Initial products phase: personalisation hasn't started yet
            new_state["suggested_replies"] = ["Personalise for me", f"Tell me more about {result.ingredient_name}"]
    else:
        new_state["suggested_replies"] = [
            f"Show me products with {result.ingredient_name}",
            "Got it, thanks!",
            "Tell me more",
        ]

    # Explicitly do NOT change: status, domain_slug, extracted_context, missing_slots,
    # initial_products, search_results, final_products, intent_type, journey_type, journey_bundle.
    new_state["next_agent"] = None  # Signal END

    logger.info(
        f"Ingredient info agent: ingredient='{result.ingredient_name}', "
        f"kg_matches={len(rough_ingredients)}, product_mentions={len(matching_products)}, "
        f"preserved_status='{current_status}'"
    )

    return new_state
