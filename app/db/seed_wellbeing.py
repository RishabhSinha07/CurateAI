"""
Seed script for Wellbeing Nutrition products.

Run with: python -m app.db.seed_wellbeing

Products are loaded from data/scraped_products_v2.json (scraped from
https://wellbeingnutrition.com/).  Domain configuration is defined inline
below because it controls AI agent behaviour (personas, slots, safety rules).
"""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from app.db.models import Product
from app.db.session import async_session_factory

# Path to the scraped product catalogue (relative to project root).
PRODUCTS_JSON = Path(__file__).resolve().parents[2] / "data" / "scraped_products_v2.json"

# =============================================================================
# NOTE: Domain configuration has been migrated to knowledge graphs
# See app/knowledge/graphs/wellness.yaml for domain metadata and configuration
# =============================================================================

# Shopify tags that are marketing noise and shouldn't be stored as attributes.
_TAGS_TO_STRIP = {"tags"}


# =============================================================================
# Product loading
# =============================================================================

def _load_products_from_json() -> list[dict]:
    """
    Read the scraped product catalogue and return a cleaned list.

    Cleaning steps:
      - Strip Shopify ``tags`` from attributes (marketing noise).
      - Convert price from float to ``Decimal``.
      - Default ``inventory_count`` to 100 (not available in scraped data).
      - Convert domain_slug to domain_slugs array for multi-domain support.
    """
    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        raw: list[dict] = json.load(f)

    products: list[dict] = []
    for item in raw:
        # Clean attributes: remove noisy fields
        attrs = {k: v for k, v in item.get("attributes", {}).items() if k not in _TAGS_TO_STRIP}

        # Convert single domain_slug to array for multi-domain support
        domain_slug = item.get("domain_slug")
        domain_slugs = [domain_slug] if domain_slug else []

        products.append(
            {
                "domain_slugs": domain_slugs,
                "sku": item["sku"],
                "name": item["name"],
                "brand": item.get("brand", "Wellbeing Nutrition"),
                "description": item.get("description"),
                "price": Decimal(str(item["price"])) if item.get("price") is not None else None,
                "currency": item.get("currency", "INR"),
                "inventory_count": 100,
                "product_url": item.get("product_url"),
                "image_url": item.get("image_url"),
                "attributes": attrs,
            }
        )

    return products


# =============================================================================
# Seeding helpers
# =============================================================================

# Domain seeding removed - domains are now managed via knowledge graphs
# See app/knowledge/graphs/*.yaml for domain configuration


async def seed_products(session, products: list[dict]) -> int:
    """Create products using domain_slugs array. Returns the count of products seeded."""
    count = 0

    for product_data in products:
        product = Product(
            domain_slugs=product_data["domain_slugs"],
            sku=product_data["sku"],
            name=product_data["name"],
            brand=product_data.get("brand"),
            description=product_data.get("description"),
            price=product_data.get("price"),
            currency=product_data.get("currency", "INR"),
            inventory_count=product_data.get("inventory_count", 100),
            product_url=product_data.get("product_url"),
            image_url=product_data.get("image_url"),
            attributes=product_data["attributes"],
        )
        session.add(product)
        count += 1

    return count


async def clear_existing_data(session) -> None:
    """Clear all existing data from tables."""
    await session.execute(text("DELETE FROM chat_messages"))
    await session.execute(text("DELETE FROM chat_sessions"))
    await session.execute(text("DELETE FROM products"))
    await session.commit()


async def seed_database() -> None:
    """Main seed function."""
    # Load products from JSON
    print(f"Loading products from {PRODUCTS_JSON} ...")
    products = _load_products_from_json()
    print(f"  Found {len(products)} products")

    async with async_session_factory() as session:
        print("Clearing existing data...")
        await clear_existing_data(session)

        print("Seeding Wellbeing Nutrition data...")

        # Seed products (domains are now managed via knowledge graphs)
        print("  Creating products...")
        count = await seed_products(session, products)
        print(f"    Created {count} products")

        await session.commit()
        print("Done!")

        # Print summary
        print("\nProducts by domain (primary domain only):")
        domain_counts: dict[str, int] = {}
        for p in products:
            # Count only the first (primary) domain
            if p["domain_slugs"]:
                primary_domain = p["domain_slugs"][0]
                domain_counts[primary_domain] = domain_counts.get(primary_domain, 0) + 1
        for slug, cnt in sorted(domain_counts.items()):
            print(f"  {slug}: {cnt} products")


if __name__ == "__main__":
    asyncio.run(seed_database())
