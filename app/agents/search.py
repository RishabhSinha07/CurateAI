from typing import Any, Dict, List
from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.config import get_settings
from app.agents.state import AgentState
from app.db.repositories.product import ProductRepository
from app.services.embeddings import generate_embedding_async
from app.knowledge.query_engine import GraphQueryEngine
from app.knowledge.graph_loader import get_knowledge_graph

settings = get_settings()
logger = logging.getLogger(__name__)


class QueryExpansion(BaseModel):
    """Structured response for query expansion."""
    expanded_query: str = Field(description="An expanded version of the user's query with synonyms and related terms")
    search_terms: List[str] = Field(description="Key search terms extracted from the context")
    filters: Dict[str, Any] = Field(description="JSONB filters to apply based on extracted context")
    reasoning: str = Field(default="", description="Brief explanation of the expansion strategy")


def get_search_model():
    """Initialize the Bedrock model for query expansion."""
    llm = ChatBedrock(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        model_kwargs={"temperature": 0},
    )
    return llm.with_structured_output(QueryExpansion)


def _build_constraint_filters(extracted_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build JSONB filters for safety-critical product constraints.

    These filters are enforced at the SQL level to guarantee that products
    violating hard user constraints (vegan diet, fish allergy) are never
    returned — regardless of semantic similarity score.
    """
    filters: Dict[str, Any] = {}
    graph_state = extracted_context.get("graph_state", {})
    filled_attrs = graph_state.get("filled_attributes", {})

    # --- Dietary preference ---
    diet = None
    if "dietary_preference" in extracted_context:
        diet = extracted_context["dietary_preference"].lower()
    # Also check graph_state filled_attributes
    for attr_cat, attr_data in filled_attrs.items():
        if attr_cat in ("diet", "dietary_preference"):
            val = attr_data.get("value", "")
            if isinstance(val, str):
                diet = val.lower()

    if diet and "vegan" in diet:
        filters["is_vegan"] = True

    # --- Fish allergy ---
    has_fish_allergy = False
    # From top-level extracted_context
    allergies = extracted_context.get("allergies", [])
    if isinstance(allergies, str):
        allergies = [allergies]
    for allergy in allergies:
        if isinstance(allergy, str) and "fish" in allergy.lower():
            has_fish_allergy = True

    # From graph_state filled_attributes
    for attr_cat, attr_data in filled_attrs.items():
        if attr_cat == "allergies":
            val = attr_data.get("value", "")
            items = val if isinstance(val, list) else [val]
            for item in items:
                if isinstance(item, str) and "fish" in item.lower():
                    has_fish_allergy = True

    if has_fish_allergy:
        filters["contains_fish"] = False

    return filters


async def search_architect_agent(state: AgentState, db: AsyncSession) -> AgentState:
    """
    Performs intelligent product search using knowledge graph and semantic search.

    This agent:
    1. Uses knowledge graph to identify relevant ingredients for the user's problem
    2. Boosts ingredients based on user attributes (e.g., iron for women)
    3. Builds search query with graph-recommended ingredients
    4. Performs hybrid vector + filter search
    """
    extracted_context = state.get("extracted_context", {})
    graph_state = extracted_context.get("graph_state", {})
    problem_id = graph_state.get("identified_problem")
    graph_domain = graph_state.get("graph_domain")

    # Build search query from problem and ingredients (not user message)
    search_query_text = None
    graph_ingredients = []

    if problem_id and graph_domain:
        try:
            # Load the knowledge graph
            graph = get_knowledge_graph(graph_domain)

            # Get problem display name for the base query
            problem_node = graph.get_node(problem_id)
            problem_display = problem_node.get('display_name', problem_id) if problem_node else problem_id

            # Get graph-recommended ingredients based on problem and user attributes
            filled_attributes = graph_state.get("filled_attributes", {})

            # Convert filled_attributes to format expected by query engine
            user_attributes = {
                attr_cat: attr_data.get("attribute_id")
                for attr_cat, attr_data in filled_attributes.items()
            }

            logger.info(f"Building graph-based search query for problem '{problem_id}' with attributes: {user_attributes}")

            graph_query = GraphQueryEngine.build_search_query(
                domain=graph_domain,
                problem_id=problem_id,
                user_attributes=user_attributes,
                boost_factor=0.2
            )

            graph_ingredient_ids = graph_query.get("primary_ingredients", [])
            logger.info(f"Graph recommended ingredient IDs: {graph_ingredient_ids}")

            # Convert ingredient IDs to display names for better semantic matching
            ingredient_display_names = []
            for ingredient_id in graph_ingredient_ids:
                ingredient_node = graph.get_node(ingredient_id)
                if ingredient_node:
                    # Use display_name or name, clean up underscores
                    display_name = ingredient_node.get('display_name') or ingredient_node.get('name', ingredient_id)
                    display_name = display_name.replace('_', ' ')
                    ingredient_display_names.append(display_name)
                else:
                    # Fallback: clean up the ID
                    ingredient_display_names.append(ingredient_id.replace('_', ' '))

            logger.info(f"Converted to display names: {ingredient_display_names}")

            # Build search query from problem + ingredient display names
            # No user message - it's just noise like "20" or "capsules"
            if ingredient_display_names:
                ingredient_str = ", ".join(ingredient_display_names)
                search_query_text = f"{problem_display}: {ingredient_str}"
            else:
                search_query_text = problem_display

            logger.info(f"Final search query: {search_query_text}")

        except Exception as e:
            logger.warning(f"Error building graph search query: {e}")
            # Fallback: use problem display name if available
            try:
                graph = get_knowledge_graph(graph_domain)
                problem_node = graph.get_node(problem_id)
                search_query_text = problem_node.get('display_name', problem_id) if problem_node else problem_id
            except:
                search_query_text = problem_id
    else:
        logger.info("No problem identified in graph_state. Using user message for search.")
        # Only fall back to user message if no problem identified
        search_query_text = state['user_message']

    if not search_query_text:
        search_query_text = state['user_message']

    # Generate embedding for the search query
    query_embedding = await generate_embedding_async(search_query_text)

    # Build hard constraint filters from extracted context
    # These are safety-critical filters (dietary, allergies) that must be
    # enforced at the SQL level — semantic similarity alone can't guarantee them.
    constraint_filters = _build_constraint_filters(extracted_context)
    if constraint_filters:
        logger.info(f"Applying constraint filters: {constraint_filters}")

    # Perform hybrid search with fallback strategy
    product_repo = ProductRepository(db)

    # Try primary threshold first (0.25 - balanced precision/recall)
    # Search across all products — domain slugs from scraped data are too broad
    # to be reliable filters; let semantic similarity do the ranking.
    search_results = await product_repo.hybrid_search(
        query_embedding=query_embedding,
        filters=constraint_filters or None,
        limit=20,
        min_similarity=0.25
    )

    # Fallback to lower threshold if we got too few results
    low_confidence_search = False
    if len(search_results) < 3:
        logger.warning(
            f"Primary search returned only {len(search_results)} results. "
            f"Attempting fallback with lower threshold (0.15)."
        )
        search_results = await product_repo.hybrid_search(
            query_embedding=query_embedding,
            filters=constraint_filters or None,
            limit=10,
            min_similarity=0.15
        )
        low_confidence_search = True

        if search_results:
            logger.info(f"Fallback search returned {len(search_results)} results.")
        else:
            logger.warning(f"No products found even with fallback threshold (0.15).")

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
    new_state["low_confidence_search"] = low_confidence_search

    return new_state
