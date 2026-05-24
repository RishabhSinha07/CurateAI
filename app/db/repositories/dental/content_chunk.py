import uuid

from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ContentChunk


class ContentChunkRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, chunk_id: uuid.UUID) -> ContentChunk | None:
        return await self.session.get(ContentChunk, chunk_id)

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        source_url: str | None = None,
        limit: int = 50,
    ) -> list[ContentChunk]:
        stmt = (
            select(ContentChunk)
            .where(
                ContentChunk.tenant_id == tenant_id,
                ContentChunk.is_active.is_(True),
            )
            .order_by(ContentChunk.source_url, ContentChunk.chunk_index)
            .limit(limit)
        )
        if source_url is not None:
            stmt = stmt.where(ContentChunk.source_url == source_url)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def search_by_embedding(
        self,
        tenant_id: uuid.UUID,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        min_similarity: float = 0.55,
    ) -> list[tuple[ContentChunk, float]]:
        """Cosine-similarity retrieval over content_chunks for a tenant.

        Returns (chunk, similarity_score) sorted descending.
        """
        similarity = (
            literal(1.0) - ContentChunk.embedding.cosine_distance(query_embedding)
        ).label("similarity")

        stmt = (
            select(ContentChunk, similarity)
            .where(
                ContentChunk.tenant_id == tenant_id,
                ContentChunk.is_active.is_(True),
                ContentChunk.embedding.is_not(None),
            )
            .order_by(similarity.desc())
            .limit(top_k)
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        return [(row[0], float(row[1])) for row in rows if row[1] is not None and row[1] >= min_similarity]
