import uuid
from typing import Any, Optional
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Product

class ProductRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        """Get a product by ID."""
        return await self.session.get(Product, product_id)

    async def hybrid_search(
        self,
        domain_id: uuid.UUID,
        query_embedding: list[float],
        filters: Optional[dict[str, Any]] = None,
        limit: int = 5,
        min_similarity: float = 0.5
    ) -> list[tuple[Product, float]]:
        """
        Perform hybrid search using vector similarity and JSONB filters.
        
        Returns a list of tuples containing (Product, similarity_score).
        """
        # Vector similarity: 1 - cosine distance
        similarity = (1 - Product.description_embedding.cosine_distance(query_embedding)).label("similarity")
        
        # Base query: active products in the specified domain
        query = select(Product, similarity).where(
            and_(
                Product.domain_id == domain_id,
                Product.is_active == True,
                Product.description_embedding.is_not(None)
            )
        )

        # Apply JSONB filters if provided
        if filters:
            for key, value in filters.items():
                if isinstance(value, (str, int, float, bool)):
                    # Exact match for scalar values
                    query = query.where(Product.attributes[key].as_string() == str(value))
                elif isinstance(value, list):
                    # For lists, check if any of the values intersect (using JSONB ?| operator)
                    # Note: SQLAlchemy's postgresql.JSONB has support for ?|
                    query = query.where(Product.attributes[key].has_any(value))

        # Filter by minimum similarity and order by score
        query = query.where(similarity >= min_similarity).order_by(similarity.desc()).limit(limit)
        
        result = await self.session.execute(query)
        return [(row[0], row[1]) for row in result.all()]

    async def get_by_ids(self, product_ids: list[uuid.UUID]) -> list[Product]:
        """Get multiple products by their IDs."""
        if not product_ids:
            return []
        result = await self.session.execute(
            select(Product).where(Product.id.in_(product_ids))
        )
        return list(result.scalars().all())
