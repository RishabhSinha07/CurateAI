import uuid

from sqlalchemy import select
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
