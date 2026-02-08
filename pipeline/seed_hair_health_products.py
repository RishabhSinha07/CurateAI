"""
Seed script for Hair Health & Growth products.

Run with: python -m pipeline.seed_hair_health_products

This script adds sample hair health products to demonstrate the hair_health_growth
knowledge graph integration.
"""

import asyncio
from decimal import Decimal
from sqlalchemy import select

from app.db.models import Product
from app.db.session import async_session_factory


# Sample hair health products aligned with the knowledge graph
HAIR_HEALTH_PRODUCTS = [
    {
        "domain_slug": "hair_health_growth",
        "sku": "HH-BIOTIN-10K",
        "name": "High-Potency Biotin 10,000mcg",
        "brand": "Hair Vitality",
        "description": "Premium biotin supplement with 10,000mcg per serving. Supports keratin production for stronger, thicker hair. Clinically proven to reduce hair fall and improve hair density within 12-16 weeks. Vegan-friendly formula.",
        "price": Decimal("599.00"),
        "currency": "INR",
        "inventory_count": 100,
        "product_url": None,
        "image_url": None,
        "attributes": {
            "product_type": "Hair Supplements",
            "format": "capsules",
            "is_vegan": True,
            "contains_fish": False,
            "ingredients": ["biotin"],
            "strength": "10000mcg",
            "category": "vitamins",
            "health_goals": ["hair_thinning", "hair_fall", "dry_damaged_hair"],
            "dosage": "1 capsule daily",
            "duration": "90 days",
        },
    },
    {
        "domain_slug": "hair_health_growth",
        "sku": "HH-SAW-PALMETTO-320",
        "name": "Saw Palmetto Extract 320mg - DHT Blocker",
        "brand": "Hair Vitality",
        "description": "Natural DHT blocker for hair thinning and pattern hair loss. Contains 320mg standardized saw palmetto extract. Helps reduce follicle shrinking caused by DHT. Ideal for men and women experiencing androgenic hair loss. Results visible in 24 weeks.",
        "price": Decimal("799.00"),
        "currency": "INR",
        "inventory_count": 100,
        "product_url": None,
        "image_url": None,
        "attributes": {
            "product_type": "Hair Supplements",
            "format": "capsules",
            "is_vegan": True,
            "contains_fish": False,
            "ingredients": ["saw_palmetto"],
            "strength": "320mg",
            "category": "herbal",
            "health_goals": ["hair_thinning"],
            "dosage": "1 capsule daily",
            "duration": "90 days",
            "gender_specific": "all",
        },
    },
    {
        "domain_slug": "hair_health_growth",
        "sku": "HH-KERATIN-COMPLEX",
        "name": "Solubilized Keratin Complex 500mg",
        "brand": "Hair Vitality",
        "description": "Bioavailable keratin peptides for hair repair and strengthening. Contains 500mg solubilized keratin that penetrates hair shaft. Repairs dry, damaged, and brittle hair from within. Improves hair elasticity and reduces breakage. Visible results in 4-8 weeks.",
        "price": Decimal("899.00"),
        "currency": "INR",
        "inventory_count": 100,
        "product_url": None,
        "image_url": None,
        "attributes": {
            "product_type": "Hair Supplements",
            "format": "capsules",
            "is_vegan": False,
            "contains_fish": False,
            "ingredients": ["keratin"],
            "strength": "500mg",
            "category": "proteins",
            "health_goals": ["dry_damaged_hair", "hair_fall"],
            "dosage": "2 capsules daily",
            "duration": "60 days",
        },
    },
    {
        "domain_slug": "hair_health_growth",
        "sku": "HH-ZINC-HAIR-30",
        "name": "Zinc for Hair Growth 30mg",
        "brand": "Hair Vitality",
        "description": "Chelated zinc supplement specifically formulated for hair health. Contains 30mg elemental zinc for hair tissue growth and repair. Supports protein synthesis and keratin formation. Gentle on stomach. Results in 8-12 weeks.",
        "price": Decimal("499.00"),
        "currency": "INR",
        "inventory_count": 100,
        "product_url": None,
        "image_url": None,
        "attributes": {
            "product_type": "Hair Supplements",
            "format": "tablets",
            "is_vegan": True,
            "contains_fish": False,
            "ingredients": ["zinc_hair"],
            "strength": "30mg",
            "category": "minerals",
            "health_goals": ["hair_fall", "hair_thinning"],
            "dosage": "1 tablet daily",
            "duration": "90 days",
        },
    },
    {
        "domain_slug": "hair_health_growth",
        "sku": "HH-COMPLETE-FORMULA",
        "name": "Complete Hair Growth Formula",
        "brand": "Hair Vitality",
        "description": "Comprehensive hair health supplement with biotin (10,000mcg), saw palmetto (160mg), zinc (15mg), horsetail extract, rosemary extract, and pumpkin seed oil. All-in-one formula for hair fall control, growth, and thickness. Suitable for all hair types.",
        "price": Decimal("1299.00"),
        "currency": "INR",
        "inventory_count": 100,
        "product_url": None,
        "image_url": None,
        "attributes": {
            "product_type": "Hair Supplements",
            "format": "capsules",
            "is_vegan": True,
            "contains_fish": False,
            "ingredients": [
                "biotin",
                "saw_palmetto",
                "zinc_hair",
                "horsetail_extract",
                "rosemary_extract",
                "pumpkin_seed_oil"
            ],
            "category": "beauty",
            "health_goals": ["hair_fall", "hair_thinning", "dry_damaged_hair"],
            "dosage": "2 capsules daily",
            "duration": "60 days",
            "gender_specific": "all",
        },
    },
    {
        "domain_slug": "hair_health_growth",
        "sku": "HH-SCALP-HEALTH",
        "name": "Scalp Health & Anti-Dandruff Formula",
        "brand": "Hair Vitality",
        "description": "Targeted formula for scalp health and dandruff control. Contains zinc (30mg), biotin (5,000mcg), rosemary extract, and horsetail extract. Supports healthy scalp environment for optimal hair growth. Reduces flaking and irritation.",
        "price": Decimal("749.00"),
        "currency": "INR",
        "inventory_count": 100,
        "product_url": None,
        "image_url": None,
        "attributes": {
            "product_type": "Hair Supplements",
            "format": "capsules",
            "is_vegan": True,
            "contains_fish": False,
            "ingredients": [
                "zinc_hair",
                "biotin",
                "rosemary_extract",
                "horsetail_extract"
            ],
            "category": "beauty",
            "health_goals": ["dandruff_scalp"],
            "dosage": "1 capsule daily",
            "duration": "90 days",
            "hair_type": ["oily", "normal"],
        },
    },
    {
        "domain_slug": "hair_health_growth",
        "sku": "HH-WOMEN-FORMULA",
        "name": "Women's Hair Health Complete",
        "brand": "Hair Vitality",
        "description": "Specially formulated for women's hair health. Contains biotin (10,000mcg), zinc (25mg), pumpkin seed oil (500mg), and horsetail extract. Addresses hormonal hair loss, thinning, and breakage. Free from hormones and harsh chemicals.",
        "price": Decimal("1199.00"),
        "currency": "INR",
        "inventory_count": 100,
        "product_url": None,
        "image_url": None,
        "attributes": {
            "product_type": "Hair Supplements",
            "format": "capsules",
            "is_vegan": True,
            "contains_fish": False,
            "ingredients": [
                "biotin",
                "zinc_hair",
                "pumpkin_seed_oil",
                "horsetail_extract"
            ],
            "category": "beauty",
            "health_goals": ["hair_fall", "hair_thinning", "dry_damaged_hair"],
            "dosage": "2 capsules daily",
            "duration": "60 days",
            "gender_specific": "female",
        },
    },
    {
        "domain_slug": "hair_health_growth",
        "sku": "HH-MEN-FORMULA",
        "name": "Men's Hair Defense Formula",
        "brand": "Hair Vitality",
        "description": "Powerful DHT-blocking formula for men. Contains saw palmetto (320mg), biotin (10,000mcg), zinc (30mg), and pumpkin seed oil (500mg). Targets male pattern hair loss and receding hairline. Natural and hormone-free.",
        "price": Decimal("1299.00"),
        "currency": "INR",
        "inventory_count": 100,
        "product_url": None,
        "image_url": None,
        "attributes": {
            "product_type": "Hair Supplements",
            "format": "capsules",
            "is_vegan": True,
            "contains_fish": False,
            "ingredients": [
                "saw_palmetto",
                "biotin",
                "zinc_hair",
                "pumpkin_seed_oil"
            ],
            "category": "beauty",
            "health_goals": ["hair_thinning", "hair_fall"],
            "dosage": "2 capsules daily",
            "duration": "90 days",
            "gender_specific": "male",
        },
    },
]


async def seed_hair_health_products() -> None:
    """Seed hair health products into the database."""
    async with async_session_factory() as session:
        print(f"Seeding {len(HAIR_HEALTH_PRODUCTS)} hair health products...")

        products_created = 0
        products_skipped = 0

        for product_data in HAIR_HEALTH_PRODUCTS:
            # Check if product already exists
            result = await session.execute(
                select(Product).where(Product.sku == product_data["sku"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"  ⊘ Skipping existing product: {product_data['name']}")
                products_skipped += 1
                continue

            # Create new product
            product = Product(
                domain_slug=product_data["domain_slug"],
                sku=product_data["sku"],
                name=product_data["name"],
                brand=product_data["brand"],
                description=product_data["description"],
                price=product_data["price"],
                currency=product_data["currency"],
                inventory_count=product_data["inventory_count"],
                product_url=product_data.get("product_url"),
                image_url=product_data.get("image_url"),
                attributes=product_data["attributes"],
            )
            session.add(product)
            print(f"  ✓ Created: {product_data['name']}")
            products_created += 1

        await session.commit()

        print(f"\n✅ Done!")
        print(f"   Created: {products_created} products")
        print(f"   Skipped: {products_skipped} products (already exist)")


async def main():
    """Main entry point."""
    print("=" * 70)
    print("Hair Health & Growth Products Seeder")
    print("=" * 70)
    print()

    await seed_hair_health_products()

    print()
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
