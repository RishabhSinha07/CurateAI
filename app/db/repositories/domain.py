import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.db.models import Domain

class DomainRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all_active(self) -> list[Domain]:
        """Get all active domains."""
        result = await self.session.execute(
            select(Domain).where(Domain.is_active == True)
        )
        return list(result.scalars().all())

    async def get_by_id(self, domain_id: uuid.UUID) -> Domain | None:
        """Get a domain by ID with parent eagerly loaded."""
        result = await self.session.execute(
            select(Domain)
            .options(selectinload(Domain.parent))
            .where(Domain.id == domain_id)
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Domain | None:
        """Get a domain by slug."""
        result = await self.session.execute(
            select(Domain).where(Domain.slug == slug)
        )
        return result.scalar_one_or_none()

    async def get_with_merged_config(self, domain_id: uuid.UUID) -> dict | None:
        """Get domain and return its config merged with parent's."""
        domain = await self.get_by_id(domain_id)
        if not domain:
            return None
        return domain.get_merged_config()
