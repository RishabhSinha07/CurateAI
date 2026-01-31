import uuid
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import JourneyBundle


class JourneyBundleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, journey_bundle_id: uuid.UUID) -> JourneyBundle | None:
        """Get a journey bundle by ID."""
        return await self.session.get(JourneyBundle, journey_bundle_id)

    async def get_by_domain(self, domain_slug: str) -> list[JourneyBundle]:
        """Get all active journey bundles for a domain."""
        result = await self.session.execute(
            select(JourneyBundle)
            .where(
                JourneyBundle.domain_slug == domain_slug,
                JourneyBundle.is_active == True
            )
            .order_by(JourneyBundle.created_at.desc())
        )
        return list(result.scalars().all())

    async def match_by_keywords(
        self,
        domain_slug: str,
        user_message: str
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
        result = await self.session.execute(
            select(JourneyBundle)
            .where(
                JourneyBundle.domain_slug == domain_slug,
                JourneyBundle.is_active == True
            )
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
        journey_id: str
    ) -> JourneyBundle | None:
        """Get a specific journey bundle by domain and journey_id."""
        result = await self.session.execute(
            select(JourneyBundle)
            .where(
                JourneyBundle.domain_slug == domain_slug,
                JourneyBundle.journey_id == journey_id,
                JourneyBundle.is_active == True
            )
        )
        return result.scalar_one_or_none()
