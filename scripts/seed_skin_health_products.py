"""
Seed script for Skin Health & Radiance products.

Run with: python -m scripts.seed_skin_health_products

This script creates sample products for the skin_health_radiance domain
with ingredients tagged from the knowledge graph.
"""

import asyncio
from decimal import Decimal
from sqlalchemy import text

from app.db.models import Product
from app.db.session import async_session_factory


# Sample products for Skin Health & Radiance domain
# Each product has ingredients tagged with IDs from the knowledge graph
SKIN_HEALTH_PRODUCTS = [
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-MC-001",
        "name": "Pure Marine Collagen Peptides",
        "brand": "Radiance Labs",
        "description": "Premium Type I & III marine collagen peptides sourced from wild-caught fish. Supports skin elasticity, hydration, and reduces the appearance of fine lines and wrinkles. Each serving provides 10g of hydrolyzed collagen for maximum absorption.",
        "price": Decimal("39.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/marine-collagen",
        "image_url": "https://example.com/images/marine-collagen.jpg",
        "attributes": {
            "ingredients": ["collagen_type_1_3_marine", "vitamin_c"],
            "format": "powder",
            "servings": 30,
            "dosage": "10g per serving",
            "primary_benefit": "skin elasticity and hydration",
            "suitable_for": ["pescatarian", "non_vegetarian"],
            "certifications": ["wild_caught", "sustainably_sourced"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-BC-001",
        "name": "Grass-Fed Bovine Collagen",
        "brand": "Radiance Labs",
        "description": "Type I & III bovine collagen from grass-fed, pasture-raised cattle. Promotes youthful skin, strengthens hair and nails, and supports joint health. Unflavored and easily mixes into beverages.",
        "price": Decimal("34.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/bovine-collagen",
        "image_url": "https://example.com/images/bovine-collagen.jpg",
        "attributes": {
            "ingredients": ["collagen_type_1_3_bovine", "vitamin_c"],
            "format": "powder",
            "servings": 30,
            "dosage": "10g per serving",
            "primary_benefit": "skin firmness and anti-aging",
            "suitable_for": ["non_vegetarian"],
            "certifications": ["grass_fed", "pasture_raised"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-VC-001",
        "name": "Vegan Collagen Builder Complex",
        "brand": "Plant Radiance",
        "description": "Plant-based collagen support formula with amino acids, silica, vitamin C, and biotin. Provides the building blocks for natural collagen synthesis. Perfect for vegans and vegetarians seeking skin health support.",
        "price": Decimal("29.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/vegan-collagen",
        "image_url": "https://example.com/images/vegan-collagen.jpg",
        "attributes": {
            "ingredients": ["vegan_collagen_builder", "vitamin_c", "silica", "biotin"],
            "format": "capsule",
            "servings": 60,
            "dosage": "2 capsules daily",
            "primary_benefit": "supports natural collagen production",
            "suitable_for": ["vegan", "vegetarian"],
            "certifications": ["vegan", "non_gmo"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-HA-001",
        "name": "Hyaluronic Acid + Vitamin C",
        "brand": "Hydra Glow",
        "description": "High-potency hyaluronic acid (200mg) combined with vitamin C for deep skin hydration and plumping. Reduces the appearance of fine lines, locks in moisture, and promotes radiant, youthful-looking skin.",
        "price": Decimal("24.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/hyaluronic-acid",
        "image_url": "https://example.com/images/hyaluronic-acid.jpg",
        "attributes": {
            "ingredients": ["hyaluronic_acid", "vitamin_c"],
            "format": "capsule",
            "servings": 60,
            "dosage": "1 capsule daily",
            "primary_benefit": "hydration and plumping",
            "suitable_for": ["vegan", "vegetarian", "non_vegetarian"],
            "certifications": ["non_gmo", "gluten_free"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-GLUT-001",
        "name": "Liposomal Glutathione 500mg",
        "brand": "Pure Radiance",
        "description": "Master antioxidant with enhanced liposomal delivery for superior absorption. Promotes luminous skin, even tone, and cellular health. Fights free radical damage and supports natural detoxification.",
        "price": Decimal("44.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/glutathione",
        "image_url": "https://example.com/images/glutathione.jpg",
        "attributes": {
            "ingredients": ["glutathione_liposomal", "vitamin_e"],
            "format": "softgel",
            "servings": 60,
            "dosage": "1 softgel daily",
            "primary_benefit": "skin brightening and antioxidant protection",
            "suitable_for": ["vegan", "vegetarian", "non_vegetarian"],
            "certifications": ["non_gmo", "soy_free"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-LIPC-001",
        "name": "Liposomal Vitamin C 1000mg",
        "brand": "Radiance Labs",
        "description": "High-absorption liposomal vitamin C for superior collagen synthesis support. Brightens skin tone, reduces hyperpigmentation, and provides powerful antioxidant protection. Enhanced bioavailability formula.",
        "price": Decimal("32.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/liposomal-vitamin-c",
        "image_url": "https://example.com/images/liposomal-vitamin-c.jpg",
        "attributes": {
            "ingredients": ["vitamin_c_liposomal"],
            "format": "softgel",
            "servings": 60,
            "dosage": "1 softgel daily",
            "primary_benefit": "collagen synthesis and brightening",
            "suitable_for": ["vegan", "vegetarian", "non_vegetarian"],
            "certifications": ["non_gmo", "gluten_free"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-ASTX-001",
        "name": "Astaxanthin 12mg - UV Shield",
        "brand": "Sun Defense",
        "description": "Nature's most powerful antioxidant derived from microalgae. Provides internal UV protection, reduces fine lines, and protects against environmental damage. Clinically proven for skin health.",
        "price": Decimal("36.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/astaxanthin",
        "image_url": "https://example.com/images/astaxanthin.jpg",
        "attributes": {
            "ingredients": ["astaxanthin", "vitamin_e"],
            "format": "softgel",
            "servings": 60,
            "dosage": "1 softgel daily",
            "primary_benefit": "UV protection and anti-aging",
            "suitable_for": ["vegan", "vegetarian", "non_vegetarian"],
            "certifications": ["vegan", "non_gmo"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-RESV-001",
        "name": "Resveratrol 500mg - Youth Activator",
        "brand": "Longevity Labs",
        "description": "Trans-resveratrol from Japanese knotweed activates longevity genes and provides powerful antioxidant protection. Reduces wrinkles, improves skin texture, and fights cellular aging.",
        "price": Decimal("28.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/resveratrol",
        "image_url": "https://example.com/images/resveratrol.jpg",
        "attributes": {
            "ingredients": ["resveratrol", "vitamin_e"],
            "format": "capsule",
            "servings": 60,
            "dosage": "1 capsule daily",
            "primary_benefit": "anti-aging and longevity",
            "suitable_for": ["vegan", "vegetarian", "non_vegetarian"],
            "certifications": ["vegan", "non_gmo"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-COQ10-001",
        "name": "CoQ10 300mg - Cellular Energy",
        "brand": "Radiance Labs",
        "description": "Ubiquinol-form CoQ10 for superior absorption. Boosts cellular energy production for vibrant, youthful skin. Powerful antioxidant that reduces oxidative stress and supports skin vitality.",
        "price": Decimal("31.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/coq10",
        "image_url": "https://example.com/images/coq10.jpg",
        "attributes": {
            "ingredients": ["coq10", "vitamin_e"],
            "format": "softgel",
            "servings": 60,
            "dosage": "1 softgel daily",
            "primary_benefit": "cellular energy and radiance",
            "suitable_for": ["vegetarian", "non_vegetarian"],
            "certifications": ["non_gmo", "gluten_free"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-ZINC-001",
        "name": "Zinc Picolinate 50mg + Copper",
        "brand": "Essential Minerals",
        "description": "Highly absorbable zinc for collagen synthesis and skin repair. Includes copper for balance. Supports wound healing, reduces inflammation, and promotes healthy skin, hair, and nails.",
        "price": Decimal("14.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/zinc",
        "image_url": "https://example.com/images/zinc.jpg",
        "attributes": {
            "ingredients": ["zinc"],
            "format": "capsule",
            "servings": 120,
            "dosage": "1 capsule daily",
            "primary_benefit": "skin repair and collagen support",
            "suitable_for": ["vegan", "vegetarian", "non_vegetarian"],
            "certifications": ["vegan", "non_gmo"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-BIOTIN-001",
        "name": "Biotin 10,000mcg - Hair, Skin & Nails",
        "brand": "Beauty Essentials",
        "description": "High-potency biotin for keratin production. Strengthens brittle nails, promotes hair growth, and supports radiant skin. Vegetarian-friendly and easy to take.",
        "price": Decimal("16.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/biotin",
        "image_url": "https://example.com/images/biotin.jpg",
        "attributes": {
            "ingredients": ["biotin"],
            "format": "capsule",
            "servings": 120,
            "dosage": "1 capsule daily",
            "primary_benefit": "hair, skin, and nail health",
            "suitable_for": ["vegan", "vegetarian", "non_vegetarian"],
            "certifications": ["vegan", "non_gmo", "gluten_free"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-OMEGA-001",
        "name": "Omega-3 EPA/DHA - Skin Hydration",
        "brand": "Marine Essentials",
        "description": "High-potency fish oil with 2000mg of EPA/DHA. Reduces inflammation, supports skin barrier function, and enhances moisture retention. Molecularly distilled for purity.",
        "price": Decimal("26.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/omega-3",
        "image_url": "https://example.com/images/omega-3.jpg",
        "attributes": {
            "ingredients": ["omega_3", "vitamin_e"],
            "format": "softgel",
            "servings": 60,
            "dosage": "2 softgels daily",
            "primary_benefit": "hydration and inflammation reduction",
            "suitable_for": ["pescatarian", "non_vegetarian"],
            "certifications": ["molecularly_distilled", "third_party_tested"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-COMBO-001",
        "name": "Radiance Complete - Beauty from Within",
        "brand": "Radiance Labs",
        "description": "Comprehensive beauty formula combining marine collagen, hyaluronic acid, vitamin C, biotin, and antioxidants. All-in-one solution for glowing skin, strong nails, and healthy hair.",
        "price": Decimal("54.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/radiance-complete",
        "image_url": "https://example.com/images/radiance-complete.jpg",
        "attributes": {
            "ingredients": [
                "collagen_type_1_3_marine",
                "hyaluronic_acid",
                "vitamin_c",
                "biotin",
                "vitamin_e",
                "zinc"
            ],
            "format": "powder",
            "servings": 30,
            "dosage": "1 scoop daily",
            "primary_benefit": "complete beauty support",
            "suitable_for": ["pescatarian", "non_vegetarian"],
            "certifications": ["third_party_tested", "gluten_free"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-VCOMBO-001",
        "name": "Vegan Beauty Essentials",
        "brand": "Plant Radiance",
        "description": "100% plant-based beauty formula with vegan collagen builder, silica from bamboo, biotin, vitamin C, and antioxidants. Complete nutrition for radiant vegan beauty.",
        "price": Decimal("42.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/vegan-beauty",
        "image_url": "https://example.com/images/vegan-beauty.jpg",
        "attributes": {
            "ingredients": [
                "vegan_collagen_builder",
                "silica",
                "biotin",
                "vitamin_c",
                "vitamin_e",
                "resveratrol"
            ],
            "format": "capsule",
            "servings": 60,
            "dosage": "2 capsules daily",
            "primary_benefit": "complete vegan beauty support",
            "suitable_for": ["vegan", "vegetarian"],
            "certifications": ["vegan", "non_gmo", "organic"]
        }
    },
    {
        "domain_slug": "skin_health_radiance",
        "sku": "SHR-ANTIOX-001",
        "name": "Antioxidant Defense Complex",
        "brand": "Pure Radiance",
        "description": "Powerful blend of glutathione, astaxanthin, resveratrol, CoQ10, and vitamins C & E. Comprehensive protection against free radicals, environmental damage, and oxidative stress.",
        "price": Decimal("48.99"),
        "currency": "USD",
        "inventory_count": 100,
        "product_url": "https://example.com/antioxidant-complex",
        "image_url": "https://example.com/images/antioxidant-complex.jpg",
        "attributes": {
            "ingredients": [
                "glutathione",
                "astaxanthin",
                "resveratrol",
                "coq10",
                "vitamin_c",
                "vitamin_e"
            ],
            "format": "capsule",
            "servings": 60,
            "dosage": "2 capsules daily",
            "primary_benefit": "antioxidant protection and anti-aging",
            "suitable_for": ["vegan", "vegetarian", "non_vegetarian"],
            "certifications": ["non_gmo", "gluten_free"]
        }
    }
]


async def seed_products(session, products: list[dict]) -> int:
    """Create products for skin health & radiance domain. Returns the count of products seeded."""
    count = 0

    for product_data in products:
        product = Product(
            domain_slug=product_data["domain_slug"],
            sku=product_data["sku"],
            name=product_data["name"],
            brand=product_data.get("brand"),
            description=product_data.get("description"),
            price=product_data.get("price"),
            currency=product_data.get("currency", "USD"),
            inventory_count=product_data.get("inventory_count", 100),
            product_url=product_data.get("product_url"),
            image_url=product_data.get("image_url"),
            attributes=product_data["attributes"],
        )
        session.add(product)
        count += 1

    return count


async def reset_skin_health_products():
    """Delete existing skin health products before seeding."""
    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM products WHERE domain_slug = 'skin_health_radiance'")
        )
        await session.commit()
        print("Deleted existing skin_health_radiance products")


async def main():
    """Main seeding function."""
    print("=" * 60)
    print("Skin Health & Radiance Product Seeding")
    print("=" * 60)

    # Reset existing products
    await reset_skin_health_products()

    # Seed products
    async with async_session_factory() as session:
        product_count = await seed_products(session, SKIN_HEALTH_PRODUCTS)
        await session.commit()
        print(f"✓ Seeded {product_count} products for skin_health_radiance domain")

    print("=" * 60)
    print("✓ Seeding complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Generate embeddings: python -m app.services.generate_embeddings")
    print("2. Test the chat API: curl -X POST http://localhost:8000/chat \\")
    print("   -H 'Content-Type: application/json' \\")
    print("   -d '{\"message\": \"I want to improve my skin elasticity\"}'")


if __name__ == "__main__":
    asyncio.run(main())
