import uuid
from typing import Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import JourneyBundle


class JourneyBundleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, journey_bundle_id: uuid.UUID) -> JourneyBundle | None:
        """Get a journey bundle by ID."""
        return await self.session.get(JourneyBundle, journey_bundle_id)

    async def get_by_domain(
        self,
        domain_slug: str,
        tenant_id: Optional[uuid.UUID] = None,
    ) -> list[JourneyBundle]:
        """Get all active journey bundles for a domain."""
        conditions = [
            JourneyBundle.domain_slug == domain_slug,
            JourneyBundle.is_active == True,
        ]
        if tenant_id:
            conditions.append(JourneyBundle.tenant_id == tenant_id)

        result = await self.session.execute(
            select(JourneyBundle)
            .where(and_(*conditions))
            .order_by(JourneyBundle.created_at.desc())
        )
        return list(result.scalars().all())

    async def match_by_keywords(
        self,
        domain_slug: str,
        user_message: str,
        tenant_id: Optional[uuid.UUID] = None,
    ) -> JourneyBundle | None:
        """
        Find journey bundle that matches keywords in user message.

        Uses PostgreSQL array overlap operator to check if any keyword
        appears in the user message (case-insensitive).

        Returns the first matching active journey bundle, or None.
        """
        # Normalize user message to lowercase for matching
        user_message_lower = user_message.lower()

        # Get all active journeys for this domain
        conditions = [
            JourneyBundle.domain_slug == domain_slug,
            JourneyBundle.is_active == True,
        ]
        if tenant_id:
            conditions.append(JourneyBundle.tenant_id == tenant_id)

        result = await self.session.execute(
            select(JourneyBundle).where(and_(*conditions))
        )
        journeys = result.scalars().all()

        # Check each journey's keywords against user message
        for journey in journeys:
            for keyword in journey.keywords:
                if keyword.lower() in user_message_lower:
                    return journey

        return None

    async def get_by_journey_id(
        self,
        domain_slug: str,
        journey_id: str,
        tenant_id: Optional[uuid.UUID] = None,
    ) -> JourneyBundle | None:
        """Get a specific journey bundle by domain and journey_id."""
        conditions = [
            JourneyBundle.domain_slug == domain_slug,
            JourneyBundle.journey_id == journey_id,
            JourneyBundle.is_active == True,
        ]
        if tenant_id:
            conditions.append(JourneyBundle.tenant_id == tenant_id)

        result = await self.session.execute(
            select(JourneyBundle).where(and_(*conditions))
        )
        return result.scalar_one_or_none()
