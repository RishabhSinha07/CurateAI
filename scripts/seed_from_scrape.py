"""
Comprehensive seed script: Scrapes Wellbeing Nutrition products and populates database.

This script:
1. Clears existing database data (clean state)
2. Creates domain hierarchy
3. Scrapes all products from Wellbeing Nutrition
4. Generates embeddings for product descriptions
5. Inserts products into database
6. Prints statistics and verification

Run with: python -m scripts.seed_from_scrape
"""

import asyncio
import sys
from pathlib import Path
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.models import Domain, Product
from app.db.session import async_session_factory
from app.services.embeddings import generate_embedding_async
from scripts.scrape_products_v2 import fetch_products_by_collection, transform_product


# =============================================================================
# DOMAIN DEFINITIONS
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
            "women's/men's health, and specialized nutrition needs."
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
            "search_filters": ["is_vegan", "is_sugar_free"],
            "safety_disclaimers": [
                "Dissolve in water and drink immediately for best results.",
            ],
        },
        "system_persona": (
            "You are a supplement specialist focusing on effervescent tablets - "
            "fizzy, refreshing supplements that dissolve in water. "
            "Help users find solutions for daily greens, immunity, gut health, and detox."
        ),
    },
    # Child: Protein (if needed)
    {
        "name": "Protein",
        "slug": "protein",
        "parent_slug": "wellness",
        "config": {
            "required_slots": ["health_goal"],
            "optional_slots": ["dietary_preference", "flavor_preference", "budget"],
            "search_filters": ["protein_type", "is_vegan"],
            "safety_disclaimers": [
                "Protein supplements support muscle recovery and growth.",
                "Use as part of a balanced diet and exercise program.",
            ],
        },
        "system_persona": (
            "You are a fitness and nutrition specialist focusing on protein supplements. "
            "Help users choose the right protein based on their fitness goals, "
            "dietary preferences (whey, plant-based), and lifestyle."
        ),
    },
]


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

async def clear_database(db: AsyncSession):
    """Clear all data from database (clean slate)."""
    print("\n" + "="*60)
    print("CLEARING DATABASE")
    print("="*60)

    # Delete in correct order (respecting foreign keys)
    await db.execute(text("TRUNCATE TABLE chat_messages CASCADE"))
    await db.execute(text("TRUNCATE TABLE chat_sessions CASCADE"))
    await db.execute(text("TRUNCATE TABLE products CASCADE"))
    await db.execute(text("TRUNCATE TABLE domains CASCADE"))
    await db.commit()

    print("✓ All tables cleared")


async def create_domains(db: AsyncSession) -> dict[str, Domain]:
    """Create domain hierarchy and return domain map."""
    print("\n" + "="*60)
    print("CREATING DOMAINS")
    print("="*60)

    domain_map = {}

    # First pass: Create root domains (no parent)
    for domain_def in DOMAINS:
        if domain_def["parent_slug"] is None:
            domain = Domain(
                name=domain_def["name"],
                slug=domain_def["slug"],
                parent_domain_id=None,
                config=domain_def["config"],
                system_persona=domain_def["system_persona"],
                is_active=True,
            )
            db.add(domain)
            domain_map[domain_def["slug"]] = domain
            print(f"  Created root domain: {domain_def['slug']}")

    await db.flush()  # Get IDs for root domains

    # Second pass: Create child domains
    for domain_def in DOMAINS:
        if domain_def["parent_slug"] is not None:
            parent = domain_map.get(domain_def["parent_slug"])
            if not parent:
                print(f"  Warning: Parent '{domain_def['parent_slug']}' not found for '{domain_def['slug']}'")
                continue

            domain = Domain(
                name=domain_def["name"],
                slug=domain_def["slug"],
                parent_domain_id=parent.id,
                config=domain_def["config"],
                system_persona=domain_def["system_persona"],
                is_active=True,
            )
            db.add(domain)
            domain_map[domain_def["slug"]] = domain
            print(f"  Created child domain: {domain_def['slug']} (parent: {domain_def['parent_slug']})")

    await db.commit()
    print(f"\n✓ Created {len(domain_map)} domains")

    return domain_map


async def scrape_and_insert_products(db: AsyncSession, domain_map: dict[str, Domain]):
    """Scrape products and insert into database with embeddings."""
    print("\n" + "="*60)
    print("SCRAPING & INSERTING PRODUCTS")
    print("="*60)

    # Scrape products by collection
    print("\nFetching products from Wellbeing Nutrition collections...")
    products_by_domain = fetch_products_by_collection()

    total_raw = sum(len(products) for products in products_by_domain.values())
    print(f"✓ Fetched {total_raw} raw products across collections")

    # Transform and filter products
    print("\nProcessing and filtering products (this may take a while)...")
    transformed_products = []

    for domain_slug, raw_products in products_by_domain.items():
        print(f"\n  Processing {domain_slug} ({len(raw_products)} products)...")
        for i, raw in enumerate(raw_products):
            if (i + 1) % 5 == 0:
                print(f"    {i + 1}/{len(raw_products)}...")

            transformed = transform_product(raw, domain_slug)
            if transformed:
                transformed_products.append(transformed)

    print(f"\n✓ Valid products after filtering: {len(transformed_products)}")

    # Insert products with embeddings
    print("\nInserting products with embeddings...")
    inserted_count = 0
    skipped_count = 0
    domain_counts = {}

    for i, product_data in enumerate(transformed_products):
        try:
            # Get domain
            domain_slug = product_data["domain_slug"]
            domain = domain_map.get(domain_slug)

            if not domain:
                print(f"  Warning: Domain '{domain_slug}' not found for product '{product_data['name']}', using 'wellness'")
                domain = domain_map.get("wellness")

            if not domain:
                print(f"  Skipping product '{product_data['name']}' - no valid domain")
                skipped_count += 1
                continue

            # Generate embedding
            description = product_data["description"]
            embedding = await generate_embedding_async(description)

            # Create product
            product = Product(
                sku=product_data["sku"],
                name=product_data["name"],
                brand=product_data["brand"],
                description=description,
                price=Decimal(str(product_data["price"])),
                currency=product_data["currency"],
                product_url=product_data["product_url"],
                image_url=product_data["image_url"],
                domain_id=domain.id,
                attributes=product_data["attributes"],
                description_embedding=embedding,
                is_active=True,
            )

            db.add(product)
            inserted_count += 1

            # Track domain counts
            domain_counts[domain_slug] = domain_counts.get(domain_slug, 0) + 1

            # Progress indicator
            if (inserted_count) % 5 == 0:
                print(f"  Inserted {inserted_count} products...")
                await db.flush()  # Periodic flush

        except Exception as e:
            print(f"  Error inserting product '{product_data.get('name', 'Unknown')}': {e}")
            skipped_count += 1
            continue

    await db.commit()

    print(f"\n✓ Inserted {inserted_count} products")
    if skipped_count > 0:
        print(f"  Skipped {skipped_count} products due to errors")

    print("\nProducts by domain:")
    for domain_slug, count in sorted(domain_counts.items()):
        print(f"  {domain_slug}: {count}")

    return inserted_count, domain_counts


async def verify_database(db: AsyncSession):
    """Verify database contents and print statistics."""
    print("\n" + "="*60)
    print("DATABASE VERIFICATION")
    print("="*60)

    # Count domains
    domain_result = await db.execute(select(Domain))
    domains = domain_result.scalars().all()
    print(f"\nTotal Domains: {len(domains)}")
    for domain in domains:
        parent_name = "None" if not domain.parent_domain_id else f"ID {domain.parent_domain_id}"
        print(f"  - {domain.slug} (parent: {parent_name})")

    # Count products
    product_result = await db.execute(select(Product))
    products = product_result.scalars().all()
    print(f"\nTotal Products: {len(products)}")

    # Products by domain
    products_by_domain = {}
    for product in products:
        domain_id = product.domain_id
        domain = next((d for d in domains if d.id == domain_id), None)
        domain_slug = domain.slug if domain else "unknown"
        products_by_domain[domain_slug] = products_by_domain.get(domain_slug, 0) + 1

    print("\nProducts by Domain:")
    for domain_slug, count in sorted(products_by_domain.items()):
        print(f"  {domain_slug}: {count}")

    # Check embeddings
    products_with_embeddings = sum(1 for p in products if p.description_embedding is not None)
    print(f"\nProducts with embeddings: {products_with_embeddings}/{len(products)}")

    # Sample products
    print("\nSample Products:")
    for product in products[:5]:
        domain = next((d for d in domains if d.id == product.domain_id), None)
        domain_slug = domain.slug if domain else "unknown"
        print(f"  - {product.name} ({domain_slug}) - ₹{product.price}")


# =============================================================================
# MAIN EXECUTION
# =============================================================================

async def main():
    """Main execution function."""
    print("\n" + "="*60)
    print("WELLBEING NUTRITION DATABASE SEEDER")
    print("="*60)
    print("\nThis script will:")
    print("  1. Clear all existing data")
    print("  2. Create domain hierarchy")
    print("  3. Scrape products from Wellbeing Nutrition")
    print("  4. Generate embeddings for all products")
    print("  5. Insert products into database")
    print("  6. Verify data integrity")
    print("\n" + "="*60)

    confirmation = input("\nProceed with database reset? (yes/no): ").strip().lower()
    if confirmation != "yes":
        print("Aborted.")
        return

    async with async_session_factory() as db:
        try:
            # Step 1: Clear database
            await clear_database(db)

            # Step 2: Create domains
            domain_map = await create_domains(db)

            # Step 3: Scrape and insert products
            inserted_count, domain_counts = await scrape_and_insert_products(db, domain_map)

            # Step 4: Verify
            await verify_database(db)

            print("\n" + "="*60)
            print("SEEDING COMPLETE")
            print("="*60)
            print(f"✓ {len(domain_map)} domains created")
            print(f"✓ {inserted_count} products inserted")
            print("\nYour database is ready for testing!")

        except Exception as e:
            print(f"\n❌ Error during seeding: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())
