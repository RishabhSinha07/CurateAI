"""
Fallback agent for out-of-domain queries.

When the Router classifies a request as out_of_scope, this agent
conversationally discovers what the user wants and searches the
entire product catalog (no domain filter).
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator

from app.agents.validators import parse_list, parse_literal_lower
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.agents.state import AgentState
from app.agents.llm import get_bedrock_llm
from app.db.repositories.product import ProductRepository
from app.services.embeddings import generate_embedding_async

logger = logging.getLogger(__name__)

MAX_FALLBACK_TURNS = 2


class FallbackResponse(BaseModel):
    """Structured response from the Fallback agent."""
    action: Literal["ask", "search"] = Field(
        default="search",
        description="Whether to ask a clarifying question or search the catalog"
    )
    search_query: Optional[str] = Field(
        default=None,
        description="The search query to use when action is 'search'"
    )
    question: Optional[str] = Field(
        default=None,
        description="The clarifying question to ask when action is 'ask'"
    )
    suggested_replies: list[str] = Field(
        default_factory=list,
        description="Quick-tap reply options for the user"
    )

    @field_validator("action", mode="before")
    @classmethod
    def normalise_action(cls, v: Any) -> Any:
        return parse_literal_lower(v)

    @field_validator("suggested_replies", mode="before")
    @classmethod
    def parse_suggested_replies(cls, v: Any) -> list:
        return parse_list(v)


def get_fallback_model():
    """Initialize the Bedrock model for fallback decisions."""
    return get_bedrock_llm(structured_output_schema=FallbackResponse)


async def fallback_agent(state: AgentState, db: AsyncSession) -> AgentState:
    """
    Handles out-of-scope queries by discovering user intent and
    searching the full product catalog.
    """
    new_state = state.copy()
    extracted_context = dict(state.get("extracted_context", {}))
    user_message = state["user_message"]

    fallback_turns = extracted_context.get("fallback_turns", 0)
    fallback_history = extracted_context.get("fallback_history", [])

    # Build conversation context for the LLM
    history_text = ""
    if fallback_history:
        history_lines = []
        for entry in fallback_history:
            if entry.get("role") == "assistant":
                history_lines.append(f"Assistant: {entry['content']}")
            else:
                history_lines.append(f"User: {entry['content']}")
        history_text = "\n".join(history_lines)

    force_search = fallback_turns >= MAX_FALLBACK_TURNS

    system_prompt = f"""You are a product discovery assistant for CurateAI. The user asked about something outside our primary domains, but we may still have relevant products in our catalog.

Your job: Decide if you have enough information to search the product catalog, or if you need to ask ONE clarifying question.

{"IMPORTANT: You have already asked enough questions. You MUST choose action='search' and construct the best search query you can from the conversation so far." if force_search else ""}

Conversation so far:
{history_text}

Current user message: "{user_message}"

Rules:
- If the user's request is specific enough to search (e.g., "I need a cordless drill", "protein powder for muscle gain"), choose action="search" and write a good search_query.
- If the request is too vague (e.g., "I want tools"), choose action="ask" and ask ONE focused question to narrow it down.
- search_query should be descriptive and natural (good for semantic/embedding search).
- suggested_replies should have 2-3 quick options the user can tap.
- Keep questions friendly and brief.
- IMPORTANT: Respond in the same language as the user's message. If the user writes in Hindi, respond in Hindi. If in English, respond in English.
"""

    model = get_fallback_model()
    result: FallbackResponse = await model.ainvoke(system_prompt)

    # Force search if we've hit the turn cap
    if force_search and result.action == "ask":
        result.action = "search"
        result.search_query = user_message

    if result.action == "search":
        search_query = result.search_query or user_message
        logger.info(f"Fallback agent searching catalog: '{search_query}'")

        # Generate embedding and search across all domains
        query_embedding = await generate_embedding_async(search_query)
        repo = ProductRepository(db)
        tenant_id = state.get("tenant_id")
        results = await repo.hybrid_search(
            query_embedding=query_embedding,
            domain_slug=None,
            limit=8,
            min_similarity=0.15,
            tenant_id=tenant_id,
        )

        if results:
            final_products = []
            for product, score in results:
                final_products.append({
                    "id": str(product.id),
                    "name": product.name,
                    "brand": product.brand,
                    "description": product.description,
                    "price": float(product.price) if product.price else None,
                    "currency": product.currency or "INR",
                    "product_url": product.product_url,
                    "image_url": product.image_url,
                    "attributes": product.attributes or {},
                    "similarity_score": round(score, 3),
                })

            new_state["final_products"] = final_products
            new_state["response"] = (
                f"Here's what I found in our catalog for \"{search_query}\"."
            )
        else:
            new_state["final_products"] = []
            new_state["response"] = (
                "I couldn't find products matching your request in our catalog. "
                "Could you try describing what you're looking for differently?"
            )

        new_state["status"] = "completed"
        new_state["next_agent"] = None
        new_state["suggested_replies"] = []

        # Clean up fallback state from context
        extracted_context.pop("fallback_turns", None)
        extracted_context.pop("fallback_history", None)
        new_state["extracted_context"] = extracted_context

    else:
        # Ask a clarifying question
        logger.info(f"Fallback agent asking: '{result.question}'")

        # Track conversation history
        if user_message:
            fallback_history.append({"role": "user", "content": user_message})
        if result.question:
            fallback_history.append({"role": "assistant", "content": result.question})

        extracted_context["fallback_turns"] = fallback_turns + 1
        extracted_context["fallback_history"] = fallback_history
        new_state["extracted_context"] = extracted_context

        new_state["response"] = result.question
        new_state["suggested_replies"] = result.suggested_replies or []
        new_state["status"] = "fallback_conversation"
        new_state["next_agent"] = None

    return new_state
