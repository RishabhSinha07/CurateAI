"""
Initial Products node — fetches a handful of products from the identified
domain so the user has something to browse while the interviewer gathers
personalisation details.

This node runs exactly once per consultation: right after the Router assigns
a domain and before the Interviewer starts asking questions.

When the Router extracted a candidate problem, this node performs a semantic
search (embedding + hybrid search) to surface relevant products.  Otherwise
it falls back to fetching the newest products in the domain.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.verticals.commerce.state import AgentState
from app.db.repositories.product import ProductRepository
from app.knowledge.graph_loader import get_knowledge_graph
from app.knowledge.query_engine import GraphQueryEngine
from app.services.embeddings import generate_embedding_async

logger = logging.getLogger(__name__)

# How many products to show in the initial showcase.
INITIAL_PRODUCT_LIMIT = 10


def _serialize_products(products) -> list[dict]:
    """Convert ORM product objects into JSON-safe dicts."""
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "brand": p.brand,
            "description": p.description,
            "price": float(p.price) if p.price else None,
            "currency": p.currency,
            "product_url": p.product_url,
            "image_url": p.image_url,
            "match_reasons": [p.description] if p.description else [],
        }
        for p in products
    ]


async def _semantic_search(
    product_repo: ProductRepository,
    domain_slug: str,
    problem_id: str,
    graph_domain: str,
    tenant_id=None,
) -> list[dict] | None:
    """
    Try to find relevant products via semantic search using the candidate
    problem's treating ingredients.  Returns ``None`` on any failure so the
    caller can fall back to the generic path.
    """
    try:
        graph = get_knowledge_graph(graph_domain)
        problem_node = graph.get_node(problem_id)
        problem_display = (
            problem_node.get("display_name", problem_id) if problem_node else problem_id
        )

        # Build a product-description-like query using ingredient names.
        # Product embeddings match ingredient names much better than
        # abstract problem labels (e.g. "iron B12 energy supplement"
        # scores ~0.4 vs "Chronic Fatigue & Low Energy" at ~0.17).
        graph_query = GraphQueryEngine.build_search_query(
            domain=graph_domain,
            problem_id=problem_id,
            user_attributes={},
        )
        ingredient_ids = graph_query.get("primary_ingredients", [])

        ingredient_names = []
        for ing_id in ingredient_ids:
            node = graph.get_node(ing_id)
            if node:
                ingredient_names.append(node.get("display_name", node.get("name", ing_id)))
            else:
                ingredient_names.append(ing_id)

        # Format as a product-like search: "iron vitamin B12 energy supplement"
        parts = ingredient_names + [problem_display, "supplement"]
        search_text = " ".join(parts)

        logger.info(f"Initial products semantic search: '{search_text}'")

        query_embedding = await generate_embedding_async(search_text)

        # Don't filter by domain_slug — product domain_slugs from scraped
        # data don't match knowledge-graph domains.  Use the same threshold
        # as the search architect (0.25).
        results = await product_repo.hybrid_search(
            query_embedding=query_embedding,
            limit=INITIAL_PRODUCT_LIMIT,
            min_similarity=0.25,
            tenant_id=tenant_id,
        )

        if results:
            # hybrid_search returns list[tuple[Product, float]]
            products = [product for product, _score in results]
            return _serialize_products(products)

    except Exception as e:
        logger.warning(f"Semantic search failed for initial products: {e}")

    return None


async def initial_products_agent(state: AgentState, db: AsyncSession) -> AgentState:
    """
    Fetch a small set of products from the newly-identified domain and
    store them in ``initial_products`` so the interviewer can present them
    alongside its first question.
    """
    domain_slug = state.get("domain_slug")
    if not domain_slug:
        # Safety guard — nothing to fetch without a domain.
        return state

    product_repo = ProductRepository(db)
    tenant_id = state.get("tenant_id")

    # --- Try semantic search using the identified problem ---
    products_data = None
    extracted_context = state.get("extracted_context", {})

    # Check graph_state first (set by interviewer after problem identification),
    # then fall back to candidate_problem (set by router).
    graph_state = extracted_context.get("graph_state", {})
    candidate = extracted_context.get("candidate_problem")

    problem_id = graph_state.get("identified_problem")
    graph_domain = graph_state.get("graph_domain")

    if problem_id and graph_domain:
        products_data = await _semantic_search(
            product_repo, domain_slug, problem_id, graph_domain,
            tenant_id=tenant_id,
        )
    elif candidate:
        products_data = await _semantic_search(
            product_repo,
            domain_slug,
            candidate["problem_id"],
            candidate["graph_domain"],
            tenant_id=tenant_id,
        )

    # --- Fallback: semantic search using the user's raw message ---
    if not products_data:
        try:
            user_msg = state.get("user_message", "")
            if user_msg:
                search_text = f"{user_msg} supplement"
                logger.info(f"Initial products fallback search: '{search_text}'")
                query_embedding = await generate_embedding_async(search_text)
                results = await product_repo.hybrid_search(
                    query_embedding=query_embedding,
                    limit=INITIAL_PRODUCT_LIMIT,
                    min_similarity=0.15,
                    tenant_id=tenant_id,
                )
                if results:
                    products = [product for product, _score in results]
                    products_data = _serialize_products(products)
        except Exception as e:
            logger.warning(f"Fallback semantic search failed: {e}")

    # --- Last resort: newest products from wellness ---
    if not products_data:
        products = await product_repo.get_by_domain("wellness", limit=INITIAL_PRODUCT_LIMIT, tenant_id=tenant_id)
        products_data = _serialize_products(products)

    # Preserve extracted_context when copying state, but remove
    # candidate_problem — it was only needed for this node's semantic
    # search and would otherwise leak into downstream prompts (interviewer
    # filled_summary, refinement preferences, DB persistence).
    # Keep a human-readable display name so the interviewer can reference
    # the concern in its warm opt-in message.
    new_state = state.copy()
    new_state["initial_products"] = products_data

    if "extracted_context" in state:
        cleaned_ctx = state["extracted_context"].copy()
        candidate = cleaned_ctx.pop("candidate_problem", None)

        # Resolve display name before discarding the candidate dict
        if candidate:
            try:
                graph = get_knowledge_graph(candidate["graph_domain"])
                node = graph.get_node(candidate["problem_id"])
                display = (
                    node.get("display_name", node.get("name", candidate["problem_id"]))
                    if node
                    else candidate["problem_id"]
                )
                cleaned_ctx["candidate_problem_display"] = display
            except Exception as e:
                logger.warning(f"Could not resolve candidate problem display name: {e}")

        new_state["extracted_context"] = cleaned_ctx

    logger.info(f"Initial products: {len(products_data)} products, extracted_context preserved")
    return new_state
