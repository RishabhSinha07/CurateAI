"""
Seed journey bundles for testing.

This script adds sample journey bundles to the database for the wellness domain.
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.db.session import async_session_factory
from app.db.models import JourneyBundle


async def seed_journey_bundles():
    """Seed sample journey bundles."""
    async with async_session_factory() as session:
        # Use wellness domain slug directly (domains now managed via knowledge graphs)
        domain_slug = 'wellness'

        print(f"Seeding journey bundles for domain: {domain_slug}")

        # Check if journey bundle already exists
        existing = await session.execute(
            select(JourneyBundle).where(
                JourneyBundle.domain_slug == domain_slug,
                JourneyBundle.journey_id == "beginner_gym"
            )
        )
        if existing.scalar_one_or_none():
            print("Journey bundle 'beginner_gym' already exists. Skipping.")
            return

        # Create beginner gym journey bundle
        journey = JourneyBundle(
            domain_slug=domain_slug,
            journey_id="beginner_gym",
            name="Starting Gym Journey",
            description="Essential products for your first month at the gym",
            keywords=[
                "starting gym",
                "new to gym",
                "beginner fitness",
                "gym starter",
                "first time gym",
                "beginning workout",
                "getting into fitness",
                "starting workout",
                "new to workout",
                "beginner at gym"
            ],
            product_categories=["protein", "pre_workout", "bcaa", "creatine"],
            product_tags=["beginner_friendly", "essential"],
            guidance_templates={
                "protein": "Take within 30 minutes after your workout to support muscle recovery and growth. Mix one scoop with water or milk for optimal absorption.",
                "pre_workout": "Consume 15-20 minutes before training for enhanced energy and focus. Start with half a serving to assess tolerance.",
                "bcaa": "Sip during workouts to reduce muscle fatigue and support endurance. Mix with water and consume throughout your training session.",
                "creatine": "Take 5g daily, either pre or post-workout. Helps increase strength and muscle mass over time. Stay well-hydrated when supplementing with creatine."
            },
            is_active=True
        )
        
        session.add(journey)
        await session.commit()
        
        print(f"✓ Created journey bundle: {journey.name}")
        print(f"  - Journey ID: {journey.journey_id}")
        print(f"  - Keywords: {', '.join(journey.keywords[:3])}...")
        print(f"  - Categories: {', '.join(journey.product_categories)}")


if __name__ == "__main__":
    print("Seeding journey bundles...\n")
    asyncio.run(seed_journey_bundles())
    print("\nDone!")
