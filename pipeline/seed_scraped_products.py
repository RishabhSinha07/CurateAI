"""
Seed the database with scraped products from Wellbeing Nutrition.

This script reads the scraped JSON file and inserts products into the database,
generating embeddings for each product.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.db.models import Domain, Product
from app.services.embeddings import generate_embedding


async def get_or_create_domains(session: AsyncSession) -> dict[str, Domain]:
    """Ensure all required domains exist and return a mapping."""

    # Check existing domains
    result = await session.execute(select(Domain))
    existing = {d.slug: d for d in result.scalars().all()}

    # Define domains we need
    required_domains = {
        "wellness": {
            "name": "Wellness",
            "slug": "wellness",
            "config": {
                "required_slots": ["health_goal"],
                "optional_slots": ["budget", "format_preference"],
                "search_filters": ["health_goal"],
                "safety_disclaimers": [
                    "These products are dietary supplements and not intended to diagnose, treat, cure, or prevent any disease.",
                    "Consult your healthcare provider before starting any supplement regimen."
                ]
            },
            "system_persona": "I'm your wellness consultant, here to help you find the right supplements for your health goals."
        },
        "melts": {
            "name": "Melts (Oral Strips)",
            "slug": "melts",
            "config": {
                "required_slots": ["health_goal"],
                "optional_slots": ["budget"],
                "search_filters": ["health_goal"],
                "safety_disclaimers": [
                    "Oral strips dissolve quickly for fast absorption.",
                    "Keep out of reach of children."
                ]
            },
            "system_persona": "I specialize in fast-dissolving oral strips for quick nutrient delivery."
        },
        "collagen": {
            "name": "Collagen",
            "slug": "collagen",
            "config": {
                "required_slots": ["skin_concern", "collagen_preference"],
                "optional_slots": ["budget", "flavor_preference"],
                "search_filters": ["collagen_type", "is_vegan"],
                "safety_disclaimers": [
                    "Marine collagen is derived from fish. Not suitable for those with fish allergies.",
                    "Results may vary. Consistent use for 8-12 weeks recommended."
                ]
            },
            "system_persona": "I'm your collagen specialist, helping you find the right formula for skin, hair, and joint health."
        },
        "slow-capsules": {
            "name": "Slow Release Capsules",
            "slug": "slow-capsules",
            "config": {
                "required_slots": ["health_goal"],
                "optional_slots": ["gender", "budget"],
                "search_filters": ["health_goal", "gender"],
                "safety_disclaimers": [
                    "Slow-release technology provides sustained nutrient delivery.",
                    "Take with food for optimal absorption."
                ]
            },
            "system_persona": "I help you find sustained-release supplements for long-lasting benefits."
        },
        "effervescent": {
            "name": "Effervescent Tablets",
            "slug": "effervescent",
            "config": {
                "required_slots": ["health_goal"],
                "optional_slots": ["flavor_preference", "budget"],
                "search_filters": ["health_goal"],
                "safety_disclaimers": [
                    "Dissolve completely in water before drinking.",
                    "Refreshing way to take your daily supplements."
                ]
            },
            "system_persona": "I specialize in fizzy, refreshing supplement drinks."
        },
        "protein": {
            "name": "Protein & Fitness",
            "slug": "protein",
            "config": {
                "required_slots": ["fitness_goal"],
                "optional_slots": ["flavor_preference", "dietary_restriction", "budget"],
                "search_filters": ["protein_type", "is_vegan"],
                "safety_disclaimers": [
                    "Protein supplements support muscle recovery and growth.",
                    "Best consumed within 30 minutes of workout."
                ]
            },
            "system_persona": "I'm your fitness nutrition expert, helping you reach your protein and fitness goals."
        },
    }

    # Create missing domains
    for slug, domain_data in required_domains.items():
        if slug not in existing:
            # Set parent to wellness for non-wellness domains
            parent_id = existing.get("wellness", None)
            if parent_id and slug != "wellness":
                parent_id = parent_id.id
            else:
                parent_id = None

            domain = Domain(
                name=domain_data["name"],
                slug=domain_data["slug"],
                parent_domain_id=parent_id,
                config=domain_data["config"],
                system_persona=domain_data["system_persona"],
                is_active=True,
            )
            session.add(domain)
            existing[slug] = domain
            print(f"  Created domain: {slug}")

    await session.flush()

    # Refresh to get IDs
    result = await session.execute(select(Domain))
    return {d.slug: d for d in result.scalars().all()}


async def seed_products(session: AsyncSession, products: list[dict], domains: dict[str, Domain]):
    """Insert products into the database."""

    # Get existing SKUs to avoid duplicates
    result = await session.execute(select(Product.sku))
    existing_skus = {row[0] for row in result.all()}

    inserted = 0
    skipped = 0
    errors = 0

    for i, product_data in enumerate(products):
        sku = product_data["sku"]
        name = product_data.get("name", "")
        domain_slug = product_data.get("domain_slug", "wellness")
        domain = domains.get(domain_slug) or domains.get("wellness")

        if not domain:
            print(f"  Warning: No domain found for {sku}, skipping")
            errors += 1
            continue

        try:
            description = product_data.get("description", "")
            
            if sku in existing_skus:
                # Update existing product URLs
                # We'll use a raw SQL update or SQLAlchemy update to refresh URLs
                print(f"  [{i+1}/{len(products)}] Updating existing: {name[:50]}...")
                stmt = (
                    select(Product)
                    .where(Product.sku == sku)
                )
                res = await session.execute(stmt)
                product = res.scalar_one()
                
                product.product_url = product_data.get("product_url")
                product.image_url = product_data.get("image_url")
                product.name = name
                product.description = description
                product.price = product_data.get("price")
                product.attributes = product_data.get("attributes", {})
                
                skipped += 1 # Counting as "updated/skipped insertion"
            else:
                # Generate embedding for the product description
                embedding_text = f"{name}. {description}"[:2000]

                print(f"  [{i+1}/{len(products)}] Inserting new: {name[:50]}...")
                embedding = generate_embedding(embedding_text)

                product = Product(
                    domain_id=domain.id,
                    sku=sku,
                    name=name,
                    brand=product_data.get("brand", "Wellbeing Nutrition"),
                    description=description,
                    price=product_data.get("price"),
                    currency=product_data.get("currency", "INR"),
                    product_url=product_data.get("product_url"),
                    image_url=product_data.get("image_url"),
                    attributes=product_data.get("attributes", {}),
                    description_embedding=embedding,
                    is_active=True,
                )
                session.add(product)
                existing_skus.add(sku)
                inserted += 1

            # Commit in batches
            if (inserted + skipped) % 10 == 0:
                await session.commit()
                print(f"    Committed batch ({inserted + skipped} total)")

        except Exception as e:
            print(f"  Error processing {sku}: {e}")
            errors += 1
            continue

    # Final commit
    await session.commit()

    return inserted, skipped, errors


async def main():
    """Main entry point."""
    print("=" * 60)
    print("Seeding Database with Scraped Products")
    print("=" * 60)

    # Load scraped products
    data_file = Path(__file__).parent / "data" / "scraped_products.json"

    if not data_file.exists():
        print(f"Error: {data_file} not found!")
        print("Run scrape_products.py first to generate the data file.")
        return

    with open(data_file, "r", encoding="utf-8") as f:
        products = json.load(f)

    print(f"Loaded {len(products)} products from {data_file}")

    async with async_session_factory() as session:
        # Ensure domains exist
        print("\nChecking domains...")
        domains = await get_or_create_domains(session)
        print(f"Available domains: {list(domains.keys())}")

        # Seed products
        print("\nSeeding products...")
        inserted, skipped, errors = await seed_products(session, products, domains)

        print("\n" + "=" * 60)
        print("Summary:")
        print(f"  Inserted: {inserted}")
        print(f"  Skipped (duplicates): {skipped}")
        print(f"  Errors: {errors}")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
