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

from app.db.models import Domain, Product
from app.db.session import async_session_factory

# Path to the scraped product catalogue (relative to project root).
PRODUCTS_JSON = Path(__file__).resolve().parents[2] / "data" / "scraped_products_v2.json"

# =============================================================================
# DOMAINS - Organized by product format and health goal
# =============================================================================

DOMAINS = [
    # Root: Wellness & Supplements
    {
        "name": "Wellness",
        "slug": "wellness",
        "parent_slug": None,
        "config": {
            "required_slots": ["health_goal"],
            "optional_slots": ["dietary_preference", "budget"],
            "search_filters": ["is_vegan", "is_sugar_free"],
            "safety_disclaimers": [
                "These products are dietary supplements and not intended to diagnose, treat, cure, or prevent any disease.",
                "Consult your healthcare provider before starting any supplement regimen.",
                "Keep out of reach of children.",
            ],
        },
        "system_persona": (
            "You are a knowledgeable wellness consultant specializing in nutritional supplements. "
            "Help users find the right supplements based on their health goals. "
            "Always recommend consulting a healthcare provider for medical conditions."
        ),
    },
    # Child: Melts (Oral Thin Strips)
    {
        "name": "Melts",
        "slug": "melts",
        "parent_slug": "wellness",
        "config": {
            "required_slots": ["health_goal"],
            "optional_slots": ["flavor_preference", "budget"],
            "search_filters": ["is_vegan", "is_sugar_free", "is_allergen_free"],
            "safety_disclaimers": [
                "Oral strips dissolve on the tongue for fast absorption.",
            ],
        },
        "system_persona": (
            "You are a supplement specialist focusing on Melts oral thin strips - "
            "a convenient, fast-absorbing format that's plant-based and sugar-free. "
            "Help users find the right Melts product for their health goals like energy, "
            "sleep, hair health, or vitamin supplementation."
        ),
    },
    # Child: Collagen
    {
        "name": "Collagen",
        "slug": "collagen",
        "parent_slug": "wellness",
        "config": {
            "required_slots": ["skin_concern", "collagen_preference"],
            "optional_slots": ["flavor_preference", "budget"],
            "search_filters": ["collagen_type", "is_vegan"],
            "safety_disclaimers": [
                "Marine collagen is derived from fish. Not suitable for those with fish allergies.",
                "Results may vary. Consistent use for 8-12 weeks recommended.",
            ],
        },
        "system_persona": (
            "You are a beauty and skin health specialist focusing on collagen supplements. "
            "Help users choose between marine collagen and vegan collagen builders based on "
            "their skin goals (anti-aging, hydration, elasticity) and dietary preferences."
        ),
    },
    # Child: Slow Capsules
    {
        "name": "Slow Capsules",
        "slug": "slow-capsules",
        "parent_slug": "wellness",
        "config": {
            "required_slots": ["health_goal", "gender"],
            "optional_slots": ["age_group", "budget"],
            "search_filters": ["target_gender", "health_category"],
            "safety_disclaimers": [
                "Slow-release capsules provide sustained nutrient delivery over 8 hours.",
                "Take with food for best absorption.",
            ],
        },
        "system_persona": (
            "You are a supplement specialist focusing on Slow Capsules - "
            "a sustained-release format that delivers nutrients over 8 hours. "
            "Help users find targeted solutions for gut health, weight management, "
            "multivitamins, and specific health conditions."
        ),
    },
    # Child: Effervescent
    {
        "name": "Effervescent",
        "slug": "effervescent",
        "parent_slug": "wellness",
        "config": {
            "required_slots": ["health_goal"],
            "optional_slots": ["flavor_preference", "budget"],
            "search_filters": ["health_category"],
            "safety_disclaimers": [
                "Dissolve tablet completely in water before drinking.",
            ],
        },
        "system_persona": (
            "You are a supplement specialist focusing on effervescent tablets - "
            "a refreshing, fast-absorbing format that dissolves in water. "
            "Help users find products for immunity, gut health, skin glow, and detox."
        ),
    },
]

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
    """
    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        raw: list[dict] = json.load(f)

    products: list[dict] = []
    for item in raw:
        # Clean attributes: remove noisy fields
        attrs = {k: v for k, v in item.get("attributes", {}).items() if k not in _TAGS_TO_STRIP}

        products.append(
            {
                "domain_slug": item["domain_slug"],
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

async def seed_domains(session) -> dict[str, Domain]:
    """Create domain hierarchy and return slug -> domain mapping."""
    slug_to_domain: dict[str, Domain] = {}

    # First pass: create all domains without parent links
    for domain_data in DOMAINS:
        domain = Domain(
            name=domain_data["name"],
            slug=domain_data["slug"],
            config=domain_data["config"],
            system_persona=domain_data["system_persona"],
        )
        session.add(domain)
        slug_to_domain[domain_data["slug"]] = domain

    await session.flush()  # Get IDs assigned

    # Second pass: set parent relationships
    for domain_data in DOMAINS:
        if domain_data["parent_slug"]:
            child = slug_to_domain[domain_data["slug"]]
            parent = slug_to_domain[domain_data["parent_slug"]]
            child.parent_domain_id = parent.id

    await session.flush()
    return slug_to_domain


async def seed_products(
    session,
    slug_to_domain: dict[str, Domain],
    products: list[dict],
) -> int:
    """Create products for each domain.  Returns the count of products seeded."""
    count = 0
    skipped: list[str] = []

    for product_data in products:
        domain = slug_to_domain.get(product_data["domain_slug"])
        if domain is None:
            skipped.append(f"{product_data['name']} (unknown domain: {product_data['domain_slug']})")
            continue

        product = Product(
            domain_id=domain.id,
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

    if skipped:
        print(f"    Skipped {len(skipped)} products (domain not found):")
        for s in skipped:
            print(f"      - {s}")

    return count


async def clear_existing_data(session) -> None:
    """Clear all existing data from tables."""
    await session.execute(text("DELETE FROM chat_messages"))
    await session.execute(text("DELETE FROM chat_sessions"))
    await session.execute(text("DELETE FROM products"))
    await session.execute(text("DELETE FROM domains"))
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

        # Seed domains
        print("  Creating domains...")
        slug_to_domain = await seed_domains(session)
        print(f"    Created {len(slug_to_domain)} domains")

        # Seed products
        print("  Creating products...")
        count = await seed_products(session, slug_to_domain, products)
        print(f"    Created {count} products")

        await session.commit()
        print("Done!")

        # Print summary
        print("\nDomain hierarchy:")
        for domain_data in DOMAINS:
            prefix = "  \u2514\u2500 " if domain_data["parent_slug"] else ""
            print(f"  {prefix}{domain_data['name']} ({domain_data['slug']})")

        print("\nProducts by domain:")
        domain_counts: dict[str, int] = {}
        for p in products:
            domain_counts[p["domain_slug"]] = domain_counts.get(p["domain_slug"], 0) + 1
        for slug, cnt in sorted(domain_counts.items()):
            print(f"  {slug}: {cnt} products")


if __name__ == "__main__":
    asyncio.run(seed_database())
