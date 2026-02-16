"""
Seed script for dummy out-of-domain products to test the fallback agent.

Run with: python -m app.db.seed_dummy

This adds a handful of non-wellness products (tools, electronics, kitchen)
so the fallback agent has something to find when searching the full catalog.
Embeddings are generated automatically.
"""

import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Product
from app.db.session import async_session_factory
from app.services.embeddings import generate_embedding_async


DUMMY_PRODUCTS = [
    {
        "domain_slugs": ["tools"],
        "sku": "DUMMY-DRILL-001",
        "name": "ProMax 20V Cordless Power Drill",
        "brand": "ProMax Tools",
        "description": (
            "A powerful 20V cordless power drill with brushless motor, "
            "2-speed gearbox, and 1/2-inch keyless chuck. Ideal for drilling "
            "into wood, metal, and masonry. Includes two lithium-ion batteries "
            "and a fast charger. Perfect for home improvement and construction projects."
        ),
        "price": Decimal("4999.00"),
        "currency": "INR",
        "inventory_count": 50,
        "product_url": None,
        "image_url": None,
        "attributes": {
            "category": "power tools",
            "voltage": "20V",
            "type": "cordless drill",
            "motor": "brushless",
        },
    },
    {
        "domain_slugs": ["tools"],
        "sku": "DUMMY-SAW-001",
        "name": "CircleCut 7-Inch Circular Saw",
        "brand": "ProMax Tools",
        "description": (
            "A lightweight 7-inch circular saw with 15-amp motor and "
            "laser guide for precise cuts. Features bevel capacity up to 56 degrees "
            "and electric brake. Great for cutting lumber, plywood, and framing materials."
        ),
        "price": Decimal("6499.00"),
        "currency": "INR",
        "inventory_count": 30,
        "product_url": None,
        "image_url": None,
        "attributes": {
            "category": "power tools",
            "type": "circular saw",
            "blade_size": "7 inch",
            "motor": "15-amp",
        },
    },
    {
        "domain_slugs": ["tools"],
        "sku": "DUMMY-HAMMER-001",
        "name": "SturdyGrip 16oz Claw Hammer",
        "brand": "SturdyGrip",
        "description": (
            "A durable 16-ounce claw hammer with fiberglass handle and "
            "shock-absorbing rubber grip. Forged steel head with smooth face "
            "for general purpose nailing and prying. Essential hand tool for "
            "any toolbox or construction site."
        ),
        "price": Decimal("899.00"),
        "currency": "INR",
        "inventory_count": 100,
        "product_url": None,
        "image_url": None,
        "attributes": {
            "category": "hand tools",
            "type": "claw hammer",
            "weight": "16oz",
        },
    },
    {
        "domain_slugs": ["electronics"],
        "sku": "DUMMY-HEADPHONES-001",
        "name": "SoundWave Pro Wireless Noise-Cancelling Headphones",
        "brand": "SoundWave",
        "description": (
            "Premium over-ear wireless headphones with active noise cancellation, "
            "40-hour battery life, and high-resolution audio drivers. Bluetooth 5.2 "
            "with multipoint connection. Comfortable memory foam ear cushions for "
            "all-day wear. Great for music, podcasts, and work calls."
        ),
        "price": Decimal("7999.00"),
        "currency": "INR",
        "inventory_count": 40,
        "product_url": None,
        "image_url": None,
        "attributes": {
            "category": "audio",
            "type": "wireless headphones",
            "battery_life": "40 hours",
            "noise_cancelling": True,
        },
    },
    {
        "domain_slugs": ["kitchen"],
        "sku": "DUMMY-BLENDER-001",
        "name": "BlendMaster 1200W High-Speed Blender",
        "brand": "BlendMaster",
        "description": (
            "A professional-grade 1200-watt high-speed blender with 6 stainless "
            "steel blades and 2-liter BPA-free jar. Variable speed control with "
            "pulse function. Perfect for smoothies, soups, nut butters, and frozen "
            "desserts. Dishwasher-safe parts for easy cleanup."
        ),
        "price": Decimal("3499.00"),
        "currency": "INR",
        "inventory_count": 60,
        "product_url": None,
        "image_url": None,
        "attributes": {
            "category": "kitchen appliances",
            "type": "blender",
            "wattage": "1200W",
            "capacity": "2L",
        },
    },
]


async def seed_dummy_products() -> None:
    """Insert dummy products and generate their embeddings."""
    async with async_session_factory() as session:
        inserted = 0
        for item in DUMMY_PRODUCTS:
            # Skip if SKU already exists
            existing = await session.execute(
                select(Product).where(Product.sku == item["sku"])
            )
            if existing.scalar_one_or_none():
                print(f"  Skipping (already exists): {item['name']}")
                continue

            product = Product(
                domain_slugs=item["domain_slugs"],
                sku=item["sku"],
                name=item["name"],
                brand=item.get("brand"),
                description=item.get("description"),
                price=item.get("price"),
                currency=item.get("currency", "INR"),
                inventory_count=item.get("inventory_count", 100),
                product_url=item.get("product_url"),
                image_url=item.get("image_url"),
                attributes=item["attributes"],
            )
            session.add(product)
            inserted += 1
            print(f"  Added: {item['name']}")

        await session.commit()
        print(f"\nInserted {inserted} dummy products.")

        # Generate embeddings for products that don't have one
        print("\nGenerating embeddings for new products...")
        result = await session.execute(
            select(Product).where(
                Product.sku.like("DUMMY-%"),
                Product.description_embedding.is_(None),
            )
        )
        products = result.scalars().all()

        for product in products:
            text_parts = [product.name]
            if product.description:
                text_parts.append(product.description)
            if product.brand:
                text_parts.append(f"Brand: {product.brand}")
            for key, val in (product.attributes or {}).items():
                text_parts.append(f"{key}: {val}")

            embed_text = " | ".join(text_parts)
            embedding = await generate_embedding_async(embed_text)
            product.description_embedding = embedding
            print(f"  Embedded: {product.name}")

        await session.commit()
        print("Done! Dummy products are ready for fallback testing.")


if __name__ == "__main__":
    asyncio.run(seed_dummy_products())
