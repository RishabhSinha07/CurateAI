"""
Quick seed script: Load products from existing scraped JSON file.

Run with: python -m scripts.seed_from_json
"""

import asyncio
import json
import sys
from pathlib import Path
from decimal import Decimal

from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.models import Domain, Product
from app.db.session import async_session_factory
from app.services.embeddings import generate_embedding_async


async def load_from_json():
    """Load products from scraped JSON and insert into database."""

    # Load scraped data
    json_file = Path(__file__).parent.parent / "data" / "scraped_products_v2.json"
    if not json_file.exists():
        print(f"Error: {json_file} not found!")
        return

    with open(json_file, "r") as f:
        products_data = json.load(f)

    print(f"Loaded {len(products_data)} products from JSON")

    async with async_session_factory() as db:
        # Get domain mapping
        domain_result = await db.execute(select(Domain))
        domains = domain_result.scalars().all()
        domain_map = {d.slug: d for d in domains}

        print(f"Found {len(domain_map)} domains in database")

        # Clear existing products
        await db.execute(text("TRUNCATE TABLE products CASCADE"))
        await db.commit()
        print("Cleared existing products")

        # Insert products
        inserted = 0
        for i, product_data in enumerate(products_data):
            try:
                domain_slug = product_data["domain_slug"]
                domain = domain_map.get(domain_slug)

                if not domain:
                    print(f"Warning: Domain '{domain_slug}' not found, skipping product")
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
                inserted += 1

                if (inserted) % 10 == 0:
                    print(f"Inserted {inserted}/{len(products_data)}...")
                    await db.flush()

            except Exception as e:
                print(f"Error inserting product {i}: {e}")
                continue

        await db.commit()
        print(f"\n✓ Successfully inserted {inserted} products")

        # Verify
        product_result = await db.execute(select(Product))
        total = len(product_result.scalars().all())
        print(f"✓ Database now has {total} products")


if __name__ == "__main__":
    asyncio.run(load_from_json())
