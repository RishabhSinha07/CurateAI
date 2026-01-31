"""
Initial Products node — fetches a handful of products from the identified
domain so the user has something to browse while the interviewer gathers
personalisation details.

This node runs exactly once per consultation: right after the Router assigns
a domain and before the Interviewer starts asking questions.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.db.repositories.product import ProductRepository

logger = logging.getLogger(__name__)

# How many products to show in the initial showcase.
INITIAL_PRODUCT_LIMIT = 4


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
    products = await product_repo.get_by_domain(domain_slug, limit=INITIAL_PRODUCT_LIMIT)

    products_data = [
        {
            "id": str(p.id),
            "name": p.name,
            "brand": p.brand,
            "description": p.description,
            "price": float(p.price) if p.price else None,
            "currency": p.currency,
            "product_url": p.product_url,
            "image_url": p.image_url,
            "match_reasons": [f"Popular in {state.get('domain_slug', 'this category')}"],
        }
        for p in products
    ]

    # Preserve extracted_context when copying state
    new_state = state.copy()
    new_state["initial_products"] = products_data

    # Ensure extracted_context is preserved from previous node (router)
    if "extracted_context" in state:
        new_state["extracted_context"] = state["extracted_context"].copy()

    logger.info(f"Initial products agent preserving extracted_context: {new_state.get('extracted_context')}")
    return new_state
