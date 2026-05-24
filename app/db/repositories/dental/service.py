import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Service


class ServiceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, service_id: uuid.UUID) -> Service | None:
        return await self.session.get(Service, service_id)

    async def get_by_slug(self, tenant_id: uuid.UUID, slug: str) -> Service | None:
        result = await self.session.execute(
            select(Service).where(
                Service.tenant_id == tenant_id,
                Service.slug == slug,
                Service.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        category: str | None = None,
        limit: int = 50,
    ) -> list[Service]:
        stmt = (
            select(Service)
            .where(Service.tenant_id == tenant_id, Service.is_active.is_(True))
            .order_by(Service.category, Service.name)
            .limit(limit)
        )
        if category is not None:
            stmt = stmt.where(Service.category == category)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
