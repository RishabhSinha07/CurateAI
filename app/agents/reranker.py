from typing import Any, Dict, List
from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.agents.state import AgentState

settings = get_settings()


class RankedProduct(BaseModel):
    """A product with its ranking information."""
    product_id: str = Field(description="The UUID of the product")
    rank: int = Field(description="Rank position where 1 is best match")
    relevance_score: float = Field(description="Score from 0.0 to 1.0")
    match_reasons: List[str] = Field(description="List of reasons why this product matches")


class RerankerResponse(BaseModel):
    """Structured response from the Reranker agent."""
    ranked_products: List[RankedProduct] = Field(
        description="Top 3-5 products ranked by relevance, best first"
    )
    excluded_products: List[str] = Field(
        default_factory=list,
        description="Product IDs that were excluded"
    )
    reasoning: str = Field(description="Brief explanation of ranking decisions")


def get_reranker_model():
    """Initialize the Bedrock model for reranking."""
    llm = ChatBedrock(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        model_kwargs={"temperature": 0},
    )
    return llm.with_structured_output(RerankerResponse)


async def reranker_agent(state: AgentState) -> AgentState:
    """
    Filters and ranks search results based on user constraints.

    This agent:
    1. Analyzes search results against user preferences
    2. Applies hard constraints (budget, allergies)
    3. Scores soft preferences (goals, format preferences)
    4. Returns top 3-5 best matching products
    """
    extracted_context = state.get("extracted_context", {})
    search_results = state.get("search_results", [])

    if not search_results:
        # No results to rank
        new_state = state.copy()
        new_state["final_products"] = []
        new_state["status"] = "completed"
        new_state["next_agent"] = "safety"
        return new_state

    # Format products for the LLM
    products_summary = []
    for i, p in enumerate(search_results):
        desc = p.get('description') or 'No description'
        desc_preview = desc[:150] if len(desc) > 150 else desc
        price = p.get('price', 0)
        currency = p.get('currency', 'INR')
        
        # Format price with correct symbol
        symbol = "₹" if currency == "INR" else "$" if currency == "USD" else ""
        price_display = f"{symbol}{price:.2f}" if symbol else f"{price:.2f} {currency}"

        summary = f"""Product {i+1}:
  - ID: {p['id']}
  - Name: {p['name']}
  - Brand: {p.get('brand', 'Unknown')}
  - Price: {price_display}
  - Description: {desc_preview}
  - Attributes: {p.get('attributes', {})}
  - Similarity Score: {p.get('similarity_score', 0):.2f}"""
        products_summary.append(summary)

    products_text = "\n\n".join(products_summary)

    system_message = """You are a Product Ranking Specialist. Analyze the candidate products and rank them based on how well they match the user's preferences. You must return a structured response with ranked_products, excluded_products, and reasoning."""

    user_message = f"""User Preferences: {extracted_context}

Candidate Products:
{products_text}

Instructions:
1. HARD CONSTRAINTS FIRST: Identify any hard constraints the user specified \
(e.g. budget/price limit, weight limit, dietary restriction, allergen). \
Products that violate ANY hard constraint MUST be excluded — add their IDs \
to excluded_products. Do NOT include them in ranked_products under any \
circumstances, even if they are otherwise a good match.
2. From the remaining products, rank from best to worst match (1 = best).
3. Select up to 5 products that best match the user's needs. If hard constraints eliminate most products, it is acceptable (and required) to return fewer than 3 products. Do not include invalid products just to fill the list.
4. For each selected product, provide the product_id (exact UUID), rank, \
relevance_score (0.0-1.0), and match_reasons.
5. Return your analysis in the required structured format."""

    model = get_reranker_model()
    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=user_message)
    ]
    result: RerankerResponse = await model.ainvoke(messages)

    # Map ranked product IDs back to full product data
    products_by_id = {p["id"]: p for p in search_results}
    final_products = []

    for ranked in result.ranked_products[:5]:  # Cap at 5
        # Double check that the product is not in the excluded list
        if ranked.product_id in result.excluded_products:
            continue

        if ranked.product_id in products_by_id:
            product_data = products_by_id[ranked.product_id].copy()
            product_data["rank"] = ranked.rank
            product_data["relevance_score"] = ranked.relevance_score
            product_data["match_reasons"] = ranked.match_reasons
            final_products.append(product_data)

    # Update state
    new_state = state.copy()
    new_state["final_products"] = final_products
    new_state["status"] = "ranked"
    new_state["next_agent"] = "safety"

    return new_state
