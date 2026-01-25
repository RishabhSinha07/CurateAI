"""
Scrape products from Wellbeing Nutrition website.

This script fetches product data from the Shopify JSON API and saves it
in a format ready for database seeding.
"""

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen, Request
from html import unescape


BASE_URL = "https://wellbeingnutrition.com"
PRODUCTS_API = f"{BASE_URL}/products.json"
COLLECTIONS_API = f"{BASE_URL}/collections.json"

# Category mappings based on product tags/types
DOMAIN_MAPPINGS = {
    "melts": ["melts", "oral strips", "melt"],
    "collagen": ["collagen", "marine collagen"],
    "slow-capsules": ["slow", "capsule", "capsules", "tablet", "tablets"],
    "effervescent": ["effervescent", "fizzy", "fizz"],
    "protein": ["protein", "whey"],
    "wellness": [],  # Default fallback
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
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html_text)
    # Decode HTML entities
    text = unescape(text)
    # Clean up whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def determine_domain(product: dict) -> str:
    """Determine which domain a product belongs to based on tags and type."""
    tags = " ".join(product.get("tags", [])).lower()
    product_type = (product.get("product_type") or "").lower()
    title = product.get("title", "").lower()

    combined = f"{tags} {product_type} {title}"

    for domain, keywords in DOMAIN_MAPPINGS.items():
        for keyword in keywords:
            if keyword in combined:
                return domain

    return "wellness"  # Default


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
        "sachet": "sachet",
    }
    title_lower = product.get("title", "").lower()
    for keyword, format_name in format_keywords.items():
        if keyword in title_lower or keyword in " ".join(tags).lower():
            attributes["format"] = format_name
            break

    # Check vegan status
    attributes["is_vegan"] = "vegan" in " ".join(tags).lower()

    # Check if contains common allergens
    attributes["contains_fish"] = any(
        kw in " ".join(tags).lower()
        for kw in ["marine", "fish", "non-vegan"]
    )

    return attributes


def fetch_all_products() -> list[dict]:
    """Fetch all products from the Shopify API with pagination."""
    all_products = []
    page = 1

    while True:
        print(f"Fetching page {page}...")
        url = f"{PRODUCTS_API}?limit=250&page={page}"

        try:
            data = fetch_json(url)
            products = data.get("products", [])

            if not products:
                break

            all_products.extend(products)
            print(f"  Found {len(products)} products (total: {len(all_products)})")

            if len(products) < 250:
                break

            page += 1
            time.sleep(0.5)  # Rate limiting

        except Exception as e:
            print(f"  Error fetching page {page}: {e}")
            break

    return all_products



def is_valid_product(product: dict) -> bool:
    """Check if the product is valid for our database."""
    title = product.get("title", "").lower()
    handle = product.get("handle", "").lower()
    
    variants = product.get("variants", [])
    if not variants:
        return False

    first_variant = variants[0]
    price = float(first_variant.get("price", 0))

    # Skip free or near-free products (e.g., 1 rupee test products)
    if price <= 1.0:
        return False

    # Skip test/placeholder products
    test_keywords = ["test", "testing", "dummy", "sample"]
    if any(kw in title for kw in test_keywords) or any(kw in handle for kw in test_keywords):
        return False

    # Skip hidden/freebie products
    tags = [t.lower() for t in product.get("tags", [])]
    if any(skip in tags for skip in ["hidden-product", "no-search", "kwikcart-freebie"]):
        return False

    # Skip free products
    if price == 0:
        return False
        
    return True


def fetch_product_details(handle: str) -> dict | None:
    """Fetch specific product details from its .js endpoint."""
    url = f"{BASE_URL}/products/{handle}.js"
    try:
        # Add delay to respect rate limits as requested
        time.sleep(1.5)
        return fetch_json(url)
    except Exception as e:
        print(f"  Warning: Could not fetch details for {handle}: {e}")
        return None


def transform_product(product: dict) -> dict | None:
    """Transform Shopify product to our database format."""
    if not is_valid_product(product):
        return None

    # Fetch official product details to get the exact URL
    handle = product.get("handle", "")
    print(f"  Fetching details for: {handle}")
    details = fetch_product_details(handle)
    
    if not details:
        print(f"  Skipping {handle} - failed to fetch details")
        return None

    # Extract info from product (using original or detailed data)
    title = product.get("title", "Unknown Product")
    variants = product.get("variants", [])
    first_variant = variants[0]
    price = float(first_variant.get("price", 0))

    # Get URL from details (it's usually relative)
    relative_url = details.get("url")
    if relative_url:
        product_url = f"{BASE_URL}{relative_url}"
    else:
        # Fallback if somehow url is missing
        from urllib.parse import quote
        product_url = f"{BASE_URL}/products/{quote(handle)}"

    # Get image from details or fallback to original
    # The .js endpoint often has 'media' or 'featured_image' or 'images'
    # We prefer the one that matches the user's request to use the 'url' endpoint source
    image_url = details.get("featured_image")
    if not image_url and details.get("images"):
        image_url = details["images"][0]
    
    # If still no image, try the original product object
    if not image_url:
        images = product.get("images", [])
        image_url = images[0].get("src") if images else None

    # Fix relative image URLs
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
        "domain_slug": determine_domain(product),
        "attributes": extract_attributes(product),
        "shopify_id": product.get("id"),
        "created_at": product.get("created_at"),
    }


def main():
    """Main entry point."""
    print("=" * 60)
    print("Wellbeing Nutrition Product Scraper")
    print("=" * 60)

    # Fetch all products
    raw_products = fetch_all_products()
    print(f"\nTotal raw products fetched: {len(raw_products)}")
    print("Processing products (this may take a while due to rate limiting)...")

    # Transform products
    products = []
    domain_counts = {}

    for i, raw in enumerate(raw_products):
        # Progress indicator
        if i % 10 == 0:
            print(f"Processing product {i+1}/{len(raw_products)}...")
            
        transformed = transform_product(raw)
        if transformed:
            products.append(transformed)
            domain = transformed["domain_slug"]
            domain_counts[domain] = domain_counts.get(domain, 0) + 1

    print(f"\nValid products after filtering: {len(products)}")
    print("\nProducts by domain:")
    for domain, count in sorted(domain_counts.items()):
        print(f"  {domain}: {count}")

    # Save to JSON file
    output_dir = Path(__file__).parent.parent / "data"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "scraped_products.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to: {output_file}")

    # Also save a summary
    summary = {
        "total_products": len(products),
        "domains": domain_counts,
        "sample_products": products[:5],
    }

    summary_file = output_dir / "scrape_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"Summary saved to: {summary_file}")

    return products


if __name__ == "__main__":
    main()
