import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Doctor


class DoctorRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, doctor_id: uuid.UUID) -> Doctor | None:
        return await self.session.get(Doctor, doctor_id)

    async def get_by_slug(self, tenant_id: uuid.UUID, slug: str) -> Doctor | None:
        result = await self.session.execute(
            select(Doctor).where(
                Doctor.tenant_id == tenant_id,
                Doctor.slug == slug,
                Doctor.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        city: str | None = None,
        gender: str | None = None,
        limit: int = 50,
    ) -> list[Doctor]:
        stmt = (
            select(Doctor)
            .where(Doctor.tenant_id == tenant_id, Doctor.is_active.is_(True))
            .order_by(Doctor.full_name)
            .limit(limit)
        )
        if city is not None:
            stmt = stmt.where(Doctor.city == city)
        if gender is not None:
            stmt = stmt.where(Doctor.gender == gender)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
