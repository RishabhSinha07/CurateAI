import uuid
from typing import Optional, Any
from sqlalchemy import select, and_, or_
from sqlalchemy.sql import literal
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
        query_embedding: list[float],
        domain_slug: Optional[str] = None,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 5,
        min_similarity: float = 0.5,
        max_price: Optional[float] = None,
        tenant_id: Optional[uuid.UUID] = None,
    ) -> list[tuple[Product, float]]:
        """
        Perform hybrid search using vector similarity and JSONB filters.

        When *domain_slug* is provided, restricts to products in that domain.
        When *tenant_id* is provided, restricts to products owned by that tenant.
        When ``None``, searches across all active products.

        Returns a list of tuples containing (Product, similarity_score).
        """
        # Vector similarity: 1 - cosine distance (using literal to avoid parameter)
        similarity = (literal(1.0) - Product.description_embedding.cosine_distance(query_embedding)).label("similarity")

        # Base query: active products with embeddings
        conditions = [
            Product.is_active == True,
            Product.description_embedding.is_not(None),
        ]
        if domain_slug:
            conditions.append(Product.domain_slugs.any(domain_slug))
        if tenant_id:
            conditions.append(Product.tenant_id == tenant_id)

        query = select(Product, similarity).where(and_(*conditions))

        # Apply JSONB filters if provided
        if filters:
            for key, value in filters.items():
                if isinstance(value, bool):
                    # JSONB booleans: compare text representation (lowercase)
                    query = query.where(
                        Product.attributes[key].as_string() == str(value).lower()
                    )
                elif isinstance(value, (str, int, float)):
                    # Exact match for scalar values
                    query = query.where(Product.attributes[key].as_string() == str(value))
                elif isinstance(value, list):
                    # For lists, check if any of the values intersect (using JSONB ?| operator)
                    # Note: SQLAlchemy's postgresql.JSONB has support for ?|
                    query = query.where(Product.attributes[key].has_any(value))

        # Apply price filter if specified (NULL prices pass through)
        if max_price is not None:
            query = query.where(
                or_(Product.price.is_(None), Product.price <= max_price)
            )

        # Filter by minimum similarity and order by score
        query = query.where(similarity >= min_similarity).order_by(similarity.desc()).limit(limit)

        result = await self.session.execute(query)
        return [(row[0], row[1]) for row in result.all()]

    async def get_by_domain(
        self,
        domain_slug: str,
        limit: int = 4,
        tenant_id: Optional[uuid.UUID] = None,
    ) -> list[Product]:
        """
        Get active products for a domain, ordered by newest first.

        Searches products that belong to the specified domain (domain can be
        in any position of the domain_slugs array).

        Used for the initial product showcase before personalised search.
        """
        conditions = [
            Product.domain_slugs.any(domain_slug),
            Product.is_active == True,
        ]
        if tenant_id:
            conditions.append(Product.tenant_id == tenant_id)

        result = await self.session.execute(
            select(Product)
            .where(and_(*conditions))
            .order_by(Product.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_ids(
        self,
        product_ids: list[uuid.UUID],
        tenant_id: Optional[uuid.UUID] = None,
    ) -> list[Product]:
        """Get multiple products by their IDs."""
        if not product_ids:
            return []
        conditions = [Product.id.in_(product_ids)]
        if tenant_id:
            conditions.append(Product.tenant_id == tenant_id)
        result = await self.session.execute(
            select(Product).where(and_(*conditions))
        )
        return list(result.scalars().all())
