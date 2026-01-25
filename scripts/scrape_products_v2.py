"""
Scrape products from Wellbeing Nutrition using ACTUAL website collections.

This improved version:
- Fetches products from actual Shopify collections (categories)
- Maps website collections to our domain structure
- More accurate than keyword-based classification

Run with: python -m scripts.scrape_products_v2
"""

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen, Request
from html import unescape


BASE_URL = "https://wellbeingnutrition.com"
COLLECTIONS_API = f"{BASE_URL}/collections.json"

# Map product_type to our domain slugs
PRODUCT_TYPE_TO_DOMAIN = {
    "Melts Strips (Adults)": "melts",
    "Melts Strips (Kids)": "melts",
    "Coffee Melts Strips": "melts",
    "Collagen Peptides": "collagen",
    "Slow Capsules": "slow-capsules",
    "Effervescent Tablets": "effervescent",
    "Whey Protein": "protein",
    "Plant Protein": "protein",
    "Protein": "protein",
    "whey": "protein",  # Lowercase whey from website
    "Superfood Plant Protein": "protein",  # Plant protein variant
}


def fetch_json(url: str) -> dict:
    """Fetch JSON from URL with rate limiting."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def clean_html(html_text: str | None) -> str:
    """Remove HTML tags and clean up text."""
    if not html_text:
        return ""
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_valid_product(product: dict) -> bool:
    """Check if the product is valid for our database."""
    title = product.get("title", "").lower()
    handle = product.get("handle", "").lower()

    variants = product.get("variants", [])
    if not variants:
        return False

    first_variant = variants[0]
    price = float(first_variant.get("price", 0))

    # Skip free or near-free products
    if price <= 1.0:
        return False

    # Skip test/placeholder products
    test_keywords = ["test", "testing", "dummy", "sample", "free sachet"]
    if any(kw in title for kw in test_keywords) or any(kw in handle for kw in test_keywords):
        return False

    # Skip hidden/freebie products
    tags = [t.lower() for t in product.get("tags", [])]
    if any(skip in tags for skip in ["hidden-product", "no-search", "kwikcart-freebie", "no-index"]):
        return False

    return True


def extract_attributes(product: dict) -> dict:
    """Extract domain-specific attributes from product data."""
    tags = product.get("tags", [])
    product_type = product.get("product_type") or ""

    attributes = {
        "product_type": product_type,
        "tags": tags,
    }

    # Extract health goals from tags
    health_keywords = ["sleep", "energy", "immunity", "digestion", "stress",
                       "weight", "skin", "hair", "bone", "muscle", "focus",
                       "detox", "gut", "heart", "liver", "brain"]
    health_goals = [kw for kw in health_keywords if any(kw in t.lower() for t in tags)]
    if health_goals:
        attributes["health_goal"] = health_goals

    # Extract format
    format_keywords = {
        "melts": "melts",
        "capsule": "capsules",
        "tablet": "tablets",
        "powder": "powder",
        "effervescent": "effervescent",
        "gummies": "gummies",
        "liquid": "liquid",
    }
    title_lower = product.get("title", "").lower()
    for keyword, format_name in format_keywords.items():
        if keyword in title_lower or keyword in " ".join(tags).lower() or keyword in product_type.lower():
            attributes["format"] = format_name
            break

    # Check vegan status
    attributes["is_vegan"] = "vegan" in " ".join(tags).lower()

    # Check allergens
    attributes["contains_fish"] = any(
        kw in " ".join(tags).lower()
        for kw in ["marine", "fish", "non-vegan"]
    )

    return attributes


def fetch_collection_products(collection_handle: str) -> list[dict]:
    """Fetch all products from a specific collection."""
    all_products = []
    page = 1

    print(f"  Fetching collection: {collection_handle}")

    while True:
        url = f"{BASE_URL}/collections/{collection_handle}/products.json?limit=250&page={page}"

        try:
            data = fetch_json(url)
            products = data.get("products", [])

            if not products:
                break

            all_products.extend(products)

            if len(products) < 250:
                break

            page += 1
            time.sleep(0.3)  # Rate limiting

        except Exception as e:
            print(f"    Warning: Error fetching page {page}: {e}")
            break

    print(f"    Found {len(all_products)} products in {collection_handle}")
    return all_products


def fetch_all_collections() -> dict:
    """Fetch all collections from Shopify."""
    print("Fetching collections from Shopify...")
    data = fetch_json(COLLECTIONS_API)
    collections = data.get("collections", [])

    collection_map = {}
    for collection in collections:
        handle = collection.get("handle")
        title = collection.get("title")
        collection_map[handle] = {
            "title": title,
            "handle": handle,
        }

    print(f"✓ Found {len(collection_map)} collections")
    return collection_map


def fetch_products_by_collection() -> dict[str, list[dict]]:
    """Fetch all products and organize by domain based on product_type."""
    print("  Fetching all products from 'all' collection...")

    # Fetch all products from the main collection
    all_products = fetch_collection_products("all")

    print(f"  ✓ Fetched {len(all_products)} total products")

    # Organize by domain based on product_type
    products_by_domain = {}
    processed_handles = set()

    for product in all_products:
        handle = product.get("handle")

        # Skip duplicates
        if handle in processed_handles:
            continue

        # Skip invalid products
        if not is_valid_product(product):
            continue

        # Determine domain from product_type
        product_type = product.get("product_type", "")
        domain_slug = PRODUCT_TYPE_TO_DOMAIN.get(product_type, "wellness")

        processed_handles.add(handle)

        if domain_slug not in products_by_domain:
            products_by_domain[domain_slug] = []

        products_by_domain[domain_slug].append(product)

    return products_by_domain


def fetch_product_details(handle: str) -> dict | None:
    """Fetch specific product details from its .js endpoint."""
    url = f"{BASE_URL}/products/{handle}.js"
    try:
        time.sleep(1.5)  # Rate limiting
        return fetch_json(url)
    except Exception as e:
        print(f"    Warning: Could not fetch details for {handle}: {e}")
        return None


def transform_product(product: dict, domain_slug: str) -> dict | None:
    """Transform Shopify product to our database format."""
    handle = product.get("handle", "")

    # Fetch product details for URL and images
    details = fetch_product_details(handle)
    if not details:
        return None

    title = product.get("title", "Unknown Product")
    variants = product.get("variants", [])
    first_variant = variants[0]
    price = float(first_variant.get("price", 0))

    # Get URL
    relative_url = details.get("url")
    if relative_url:
        product_url = f"{BASE_URL}{relative_url}"
    else:
        from urllib.parse import quote
        product_url = f"{BASE_URL}/products/{quote(handle)}"

    # Get image
    image_url = details.get("featured_image")
    if not image_url and details.get("images"):
        image_url = details["images"][0]
    if not image_url:
        images = product.get("images", [])
        image_url = images[0].get("src") if images else None

    # Fix relative URLs
    if image_url and image_url.startswith("//"):
        image_url = f"https:{image_url}"

    # Clean description
    description = clean_html(product.get("body_html"))
    if len(description) > 2000:
        description = description[:1997] + "..."

    return {
        "sku": first_variant.get("sku") or f"WBN-{product['id']}",
        "name": title,
        "brand": product.get("vendor", "Wellbeing Nutrition"),
        "description": description,
        "price": price,
        "currency": "INR",
        "product_url": product_url,
        "image_url": image_url,
        "domain_slug": domain_slug,  # From collection mapping!
        "attributes": extract_attributes(product),
        "shopify_id": product.get("id"),
        "created_at": product.get("created_at"),
    }


def main():
    """Main entry point."""
    print("=" * 60)
    print("Wellbeing Nutrition Product Scraper (Product Type-based)")
    print("=" * 60)

    # Fetch all products and organize by domain
    print("\nFetching all products...")
    products_by_domain = fetch_products_by_collection()

    print("\nProducts found by domain:")
    for domain, products in sorted(products_by_domain.items()):
        print(f"  {domain}: {len(products)} products")

    # Transform all products
    print("\nProcessing products (fetching details)...")
    all_transformed = []
    domain_counts = {}

    for domain_slug, products in products_by_domain.items():
        print(f"\nProcessing {domain_slug} products...")
        for i, product in enumerate(products):
            if (i + 1) % 5 == 0:
                print(f"  {i + 1}/{len(products)}...")

            transformed = transform_product(product, domain_slug)
            if transformed:
                all_transformed.append(transformed)
                domain_counts[domain_slug] = domain_counts.get(domain_slug, 0) + 1

    print(f"\n✓ Total valid products: {len(all_transformed)}")
    print("\nFinal counts by domain:")
    for domain, count in sorted(domain_counts.items()):
        print(f"  {domain}: {count}")

    # Save to JSON
    output_dir = Path(__file__).parent.parent / "data"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "scraped_products_v2.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_transformed, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Saved to: {output_file}")

    # Summary
    summary = {
        "total_products": len(all_transformed),
        "domains": domain_counts,
        "sample_products": all_transformed[:5],
    }

    summary_file = output_dir / "scrape_summary_v2.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"✓ Summary saved to: {summary_file}")

    return all_transformed


if __name__ == "__main__":
    main()
