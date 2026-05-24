import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Clinic


class ClinicRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, clinic_id: uuid.UUID) -> Clinic | None:
        return await self.session.get(Clinic, clinic_id)

    async def get_by_slug(self, tenant_id: uuid.UUID, slug: str) -> Clinic | None:
        result = await self.session.execute(
            select(Clinic).where(
                Clinic.tenant_id == tenant_id,
                Clinic.slug == slug,
                Clinic.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        city: str | None = None,
        limit: int = 50,
    ) -> list[Clinic]:
        stmt = (
            select(Clinic)
            .where(Clinic.tenant_id == tenant_id, Clinic.is_active.is_(True))
            .order_by(Clinic.city, Clinic.name)
            .limit(limit)
        )
        if city is not None:
            stmt = stmt.where(Clinic.city == city)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
