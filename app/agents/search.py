from typing import Any, Dict, List
from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.agents.state import AgentState
from app.db.repositories.product import ProductRepository
from app.services.embeddings import generate_embedding_async

settings = get_settings()


class QueryExpansion(BaseModel):
    """Structured response for query expansion."""
    expanded_query: str = Field(description="An expanded version of the user's query with synonyms and related terms")
    search_terms: List[str] = Field(description="Key search terms extracted from the context")
    filters: Dict[str, Any] = Field(description="JSONB filters to apply based on extracted context")
    reasoning: str = Field(description="Brief explanation of the expansion strategy")


def get_search_model():
    """Initialize the Bedrock model for query expansion."""
    llm = ChatBedrock(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        model_kwargs={"temperature": 0},
    )
    return llm.with_structured_output(QueryExpansion)


async def search_architect_agent(state: AgentState, db: AsyncSession) -> AgentState:
    """
    Expands user query and performs hybrid search to find relevant products.

    This agent:
    1. Analyzes the extracted context and user intent
    2. Expands the query with synonyms and related terms
    3. Maps context values to JSONB filters
    4. Performs hybrid vector + filter search
    """
    domain_config = state.get("domain_config") or {}
    extracted_context = state.get("extracted_context", {})
    search_filters = domain_config.get("search_filters", [])

    # Build the expansion prompt
    system_prompt = f"""You are a Search Query Architect for CurateAI, a wellness product recommendation system.

Your task is to optimize the search query for finding the best matching products.

Domain: {state.get('domain_slug')}
User's Original Message: "{state['user_message']}"
Extracted User Preferences: {extracted_context}
Available Filter Fields: {search_filters}

Your Tasks:
1. EXPAND: Create an expanded natural language query that captures the user's intent with synonyms and related terms. This will be used for semantic (vector) search. Include the user's concerns, goals, and preferences.
2. EXTRACT: Identify key search terms that should match product descriptions.
3. FILTER: Only create filters for fields that are EXACTLY in the Available Filter Fields list. If a preference doesn't match an available filter field, do NOT create a filter for it - rely on semantic search instead.

IMPORTANT RULES FOR FILTERS:
- Only use filter field names from: {search_filters}
- If the list is empty or preferences don't match, return an empty filters object {{}}
- Do NOT create filters for fields like "skin_concern", "format", "collagen_preference" unless they are in the Available Filter Fields
- When in doubt, use an empty filter and let semantic search handle it
"""

    model = get_search_model()
    result: QueryExpansion = await model.ainvoke(system_prompt)

    # Generate embedding for the expanded query
    query_embedding = await generate_embedding_async(result.expanded_query)

    # Perform hybrid search (rely on semantic search, let reranker filter)
    product_repo = ProductRepository(db)
    search_results = await product_repo.hybrid_search(
        domain_id=state["domain_id"],
        query_embedding=query_embedding,
        filters=None,  # Skip JSONB filters, use semantic search + reranker
        limit=20,
        min_similarity=0.3
    )

    # Convert results to serializable format
    products_data = []
    for product, similarity in search_results:
        products_data.append({
            "id": str(product.id),
            "name": product.name,
            "brand": product.brand,
            "description": product.description,
            "price": float(product.price) if product.price else None,
            "currency": product.currency,
            "product_url": product.product_url,
            "image_url": product.image_url,
            "attributes": product.attributes,
            "similarity_score": float(similarity)
        })

    # Update state
    new_state = state.copy()
    new_state["search_results"] = products_data
    new_state["status"] = "searching"
    new_state["next_agent"] = "reranker"

    return new_state
