"""
Tag existing Wellbeing Nutrition products with knowledge graph ingredient IDs.

This script reads the existing scraped products and intelligently maps them
to ingredient IDs from the skin_health_radiance and hair_health_growth
knowledge graphs based on product names and descriptions.

Run with:
  python -m scripts.tag_existing_products                    # Tag all domains
  python -m scripts.tag_existing_products --domain skin      # Skin health only
  python -m scripts.tag_existing_products --domain hair      # Hair health only
"""

import asyncio
import json
import sys
from pathlib import Path
from decimal import Decimal
from sqlalchemy import text

from app.db.models import Product
from app.db.session import async_session_factory


# ============================================================================
# SKIN HEALTH MAPPINGS
# ============================================================================
SKIN_INGREDIENT_MAPPINGS = {
    # Collagen products
    "marine collagen": ["collagen_type_1_3_marine", "vitamin_c"],
    "pure korean marine collagen": ["collagen_type_1_3_marine"],
    "beauty collagen": ["collagen_type_1_3_marine", "hyaluronic_acid", "biotin"],
    "glow collagen": ["collagen_type_1_3_marine", "glutathione_liposomal", "vitamin_c"],
    "matcha collagen": ["collagen_type_1_3_marine", "vitamin_e"],
    "vegan pro collagen": ["vegan_collagen_builder", "vitamin_c", "silica"],

    # Glutathione products
    "glutathione skin fuel": ["glutathione_liposomal", "vitamin_c", "vitamin_e"],
    "glutathione": ["glutathione"],

    # Vitamin products
    "vitamin c": ["vitamin_c", "zinc"],
    "vitamin e": ["vitamin_e"],
    "biotin": ["biotin"],
    "b complex": ["biotin", "vitamin_c"],
}

SKIN_KEYWORD_INGREDIENTS = {
    "collagen": "collagen_type_1_3_marine",
    "glutathione": "glutathione",
    "vitamin c": "vitamin_c",
    "biotin": "biotin",
    "hyaluronic": "hyaluronic_acid",
    "zinc": "zinc",
    "matcha": "vitamin_e",
    "vegan": "vegan_collagen_builder",
}

# ============================================================================
# HAIR HEALTH MAPPINGS
# ============================================================================
HAIR_INGREDIENT_MAPPINGS = {
    # Hair-specific products
    "hair biotin": ["biotin"],
    "hair growth": ["biotin", "saw_palmetto", "zinc_hair"],
    "hair fall control": ["biotin", "zinc_hair"],
    "hair keratin": ["keratin"],
    "saw palmetto": ["saw_palmetto"],
    "pumpkin seed": ["pumpkin_seed_oil"],
    "horsetail": ["horsetail_extract"],
    "rosemary": ["rosemary_extract"],

    # Shared with skin health
    "biotin": ["biotin"],
    "zinc": ["zinc_hair"],
    "keratin": ["keratin"],
}

HAIR_KEYWORD_INGREDIENTS = {
    "biotin": "biotin",
    "saw palmetto": "saw_palmetto",
    "keratin": "keratin",
    "rosemary": "rosemary_extract",
    "zinc": "zinc_hair",
    "pumpkin seed": "pumpkin_seed_oil",
    "horsetail": "horsetail_extract",
    "silica": "horsetail_extract",
    "collagen": "collagen_type_1_3_marine",  # collagen also helps hair
}


def detect_ingredients(
    product_name: str,
    description: str,
    domain_type: str = "skin",
    is_vegan: bool = False
) -> list[str]:
    """
    Intelligently detect ingredient IDs based on product name and description.

    Args:
        product_name: Product name
        description: Product description
        domain_type: "skin" or "hair"
        is_vegan: Whether product is vegan

    Returns:
        List of ingredient IDs from the knowledge graph
    """
    ingredients = set()
    name_lower = product_name.lower()
    desc_lower = (description or "").lower()
    combined = f"{name_lower} {desc_lower}"

    # Select appropriate mappings based on domain
    if domain_type == "hair":
        exact_mappings = HAIR_INGREDIENT_MAPPINGS
        keyword_mappings = HAIR_KEYWORD_INGREDIENTS
    else:
        exact_mappings = SKIN_INGREDIENT_MAPPINGS
        keyword_mappings = SKIN_KEYWORD_INGREDIENTS

    # First, check exact mappings (highest priority)
    for keyword, ingredient_list in exact_mappings.items():
        if keyword in name_lower:
            if isinstance(ingredient_list, list):
                ingredients.update(ingredient_list)
            else:
                ingredients.add(ingredient_list)

    # If vegan, ensure we use vegan collagen builder
    if is_vegan and any(ing.startswith("collagen_") for ing in ingredients):
        ingredients = {ing for ing in ingredients if not ing.startswith("collagen_")}
        ingredients.add("vegan_collagen_builder")

    # Check for additional keywords
    if len(ingredients) < 2:
        for keyword, ingredient_id in keyword_mappings.items():
            if keyword in combined:
                ingredients.add(ingredient_id)

    # If it's a collagen product but we haven't tagged collagen yet
    if "collagen" in combined and not any("collagen" in ing for ing in ingredients):
        if is_vegan:
            ingredients.add("vegan_collagen_builder")
        else:
            ingredients.add("collagen_type_1_3_marine")

    return list(ingredients)


def should_include_product_for_skin(product_name: str, domain_slug: str) -> bool:
    """
    Determine if a product is relevant for skin health & radiance domain.

    Args:
        product_name: Product name
        domain_slug: Current domain slug

    Returns:
        True if product should be included in skin_health_radiance domain
    """
    name_lower = product_name.lower()

    # Include all collagen domain products
    if domain_slug == "collagen":
        return True

    # Include specific skin-health products from other domains
    skin_keywords = [
        "collagen", "glutathione", "glow", "beauty",
        "skin", "radiance", "vitamin c", "vitamin e",
        "hyaluronic", "anti-aging", "elasticity"
    ]

    return any(keyword in name_lower for keyword in skin_keywords)


def should_include_product_for_hair(product_name: str, domain_slug: str, description: str = "") -> bool:
    """
    Determine if a product is relevant for hair health & growth domain.

    Args:
        product_name: Product name
        domain_slug: Current domain slug
        description: Product description

    Returns:
        True if product should be included in hair_health_growth domain
    """
    name_lower = product_name.lower()
    desc_lower = (description or "").lower()
    combined = f"{name_lower} {desc_lower}"

    # Hair-specific keywords
    hair_keywords = [
        "hair", "biotin", "keratin", "saw palmetto",
        "hair fall", "hair growth", "hair loss", "scalp",
        "thinning", "hair health", "follicle", "dht"
    ]

    return any(keyword in combined for keyword in hair_keywords)


async def tag_existing_products(domain_filter: str = "all"):
    """
    Read existing products from JSON and update them with ingredient tags
    for skin_health_radiance and/or hair_health_growth domains.

    Args:
        domain_filter: "all", "skin", or "hair"
    """
    # Load products from JSON
    products_json = Path(__file__).resolve().parents[1] / "data" / "scraped_products_v2.json"

    with open(products_json, 'r') as f:
        products = json.load(f)

    print(f"Loaded {len(products)} products from JSON")
    print(f"Tagging for: {domain_filter}\n")

    tagged_products = []

    for product in products:
        product_name = product.get('name', '')
        domain_slug = product.get('domain_slug', '')
        description = product.get('description', '')
        is_vegan = product.get('attributes', {}).get('is_vegan', False)

        # Determine which domains this product should be tagged for
        for_skin = should_include_product_for_skin(product_name, domain_slug)
        for_hair = should_include_product_for_hair(product_name, domain_slug, description)

        # Apply domain filter
        if domain_filter == "skin" and not for_skin:
            continue
        elif domain_filter == "hair" and not for_hair:
            continue
        elif domain_filter == "all" and not (for_skin or for_hair):
            continue

        # Tag for skin health
        if for_skin and domain_filter in ["all", "skin"]:
            skin_ingredients = detect_ingredients(
                product_name, description, domain_type="skin", is_vegan=is_vegan
            )

            if skin_ingredients:
                skin_product = {
                    "domain_slug": "skin_health_radiance",
                    "sku": product.get('sku') + "-SKIN",
                    "name": product.get('name'),
                    "brand": product.get('brand', 'Wellbeing Nutrition'),
                    "description": product.get('description'),
                    "price": Decimal(str(product['price'])) if product.get('price') else None,
                    "currency": product.get('currency', 'INR'),
                    "inventory_count": 100,
                    "product_url": product.get('product_url'),
                    "image_url": product.get('image_url'),
                    "attributes": {
                        **product.get('attributes', {}),
                        "ingredients": skin_ingredients,
                        "original_domain": domain_slug,
                    }
                }
                tagged_products.append(skin_product)
                print(f"✓ [SKIN] {product_name}")
                print(f"  Ingredients: {skin_ingredients}\n")

        # Tag for hair health
        if for_hair and domain_filter in ["all", "hair"]:
            hair_ingredients = detect_ingredients(
                product_name, description, domain_type="hair", is_vegan=is_vegan
            )

            if hair_ingredients:
                hair_product = {
                    "domain_slug": "hair_health_growth",
                    "sku": product.get('sku') + "-HAIR",
                    "name": product.get('name'),
                    "brand": product.get('brand', 'Wellbeing Nutrition'),
                    "description": product.get('description'),
                    "price": Decimal(str(product['price'])) if product.get('price') else None,
                    "currency": product.get('currency', 'INR'),
                    "inventory_count": 100,
                    "product_url": product.get('product_url'),
                    "image_url": product.get('image_url'),
                    "attributes": {
                        **product.get('attributes', {}),
                        "ingredients": hair_ingredients,
                        "original_domain": domain_slug,
                    }
                }
                tagged_products.append(hair_product)
                print(f"✓ [HAIR] {product_name}")
                print(f"  Ingredients: {hair_ingredients}\n")

    return tagged_products


async def seed_products(session, products: list[dict]) -> int:
    """Create products for skin health & radiance domain."""
    count = 0

    for product_data in products:
        product = Product(
            domain_slug=product_data["domain_slug"],
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


async def reset_skin_health_products(skus: list[str]):
    """Delete existing products that will be re-tagged to skin_health_radiance domain."""
    async with async_session_factory() as session:
        # Delete by SKU to handle products that may exist in other domains
        sku_list = ','.join([f"'{sku}'" for sku in skus])
        await session.execute(
            text(f"DELETE FROM products WHERE sku IN ({sku_list})")
        )
        await session.commit()
        print(f"Deleted {len(skus)} existing products by SKU")


async def main():
    """Main function."""
    # Parse command line arguments
    domain_filter = "all"
    if len(sys.argv) > 1:
        if "--domain" in sys.argv:
            idx = sys.argv.index("--domain")
            if idx + 1 < len(sys.argv):
                filter_arg = sys.argv[idx + 1].lower()
                if filter_arg in ["skin", "hair", "all"]:
                    domain_filter = filter_arg
                else:
                    print(f"Invalid domain filter: {filter_arg}")
                    print("Valid options: skin, hair, all")
                    return

    print("=" * 70)
    print("Tagging Existing Wellbeing Nutrition Products")
    print(f"Domain Filter: {domain_filter.upper()}")
    print("=" * 70)
    print()

    # Tag products
    products = await tag_existing_products(domain_filter=domain_filter)

    if not products:
        print("\n❌ No products found to tag!")
        return

    # Group by domain
    domain_counts = {}
    for p in products:
        domain = p['domain_slug']
        domain_counts[domain] = domain_counts.get(domain, 0) + 1

    print(f"\n✓ Tagged {len(products)} products")
    for domain, count in domain_counts.items():
        print(f"  {domain}: {count} products")

    # Collect SKUs for deletion
    skus = [p['sku'] for p in products]

    # Reset existing products with these SKUs
    await reset_skin_health_products(skus)

    # Seed to database
    async with async_session_factory() as session:
        product_count = await seed_products(session, products)
        await session.commit()
        print(f"\n✓ Seeded {product_count} products to database")

    print("\n" + "=" * 70)
    print("✓ Tagging complete!")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Generate embeddings: python -m app.services.generate_embeddings")
    print("2. Test queries:")
    print("   - Skin: 'I want to improve my skin elasticity'")
    print("   - Hair: 'I'm experiencing hair fall and thinning'")


if __name__ == "__main__":
    asyncio.run(main())
