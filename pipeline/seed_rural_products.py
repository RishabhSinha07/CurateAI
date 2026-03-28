"""
Seed script for Rural Equip agricultural products.

Two-step process:
  1. (Local, one-time) Convert Excel → JSON:
       python -m pipeline.seed_rural_products --export-json
  2. (Docker) Seed DB from JSON:
       docker compose exec app python -m pipeline.seed_rural_products

The JSON intermediate file (pipeline/data/rural_products.json) is checked in
so the Docker container doesn't need openpyxl.

Embeddings are NOT generated here — run `python -m app.services.generate_embeddings`
separately after seeding.
"""

import asyncio
import json
import re
import sys
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.models import Product
from app.db.session import async_session_factory

# Rural Equip tenant (created via scripts/create_tenant.py)
RURAL_TENANT_ID = uuid.UUID("6a77550b-d69b-4f8c-ba73-6436aac988f9")

# Path to the Excel export from Rural Equip's MySQL database.
EXCEL_PATH = Path(__file__).resolve().parents[1] / ".." / "cai-clients" / "Product list from db.xlsx"

# Pre-exported JSON (works inside Docker without openpyxl).
PRODUCTS_JSON = Path(__file__).resolve().parent / "data" / "rural_products.json"

# Domain slug for all rural products.
RURAL_DOMAIN = "rural-equipment"

# ============================================================================
# Category mapping (category_id → human-readable name)
# Derived from inspecting product names grouped by category_id in the Excel.
# ============================================================================

CATEGORY_MAP: dict[int, str] = {
    19: "Power Tillers & Engines",
    42: "Brush Cutters & Trimmers",
    46: "Shade Nets & Covers",
    47: "Water Pumps",
    48: "Sprayers",
    49: "Earth Augers & Tree Planters",
    51: "Chaff Cutters & Chippers",
    52: "Seeders",
    54: "Engines & Motors",
    55: "Reapers & Harvesters",
    56: "Chainsaws",
    60: "Pressure Washers & Air Tools",
    62: "Generators",
    70: "Processing Equipment",
    71: "Lighting & Torches",
    76: "Combo Packages",
}

SUBCATEGORY_MAP: dict[int, str] = {
    # Brush Cutters & Trimmers (cat 42)
    41: "Brush Cutters",
    42: "Trimmer Lines",
    51: "Trimmer Heads",
    79: "Brush Cutter Spare Parts",
    80: "Brush Cutter Accessories",
    81: "Brush Cutter Attachments",
    85: "Hedge Trimmers",
    # Power Tillers & Engines (cat 19)
    48: "Power Tillers",
    49: "Mini Tillers",
    50: "Tiller Engine Parts",
    52: "Rotary Tillers",
    53: "Power Weeders",
    54: "Stubble Mowers",
    58: "Chain Cultivators",
    84: "Inter Cultivators",
    103: "Tiller Spare Parts",
    # Shade Nets & Covers (cat 46)
    43: "Shade Nets (Green)",
    44: "Shade Nets (Colored)",
    45: "Shade Nets (Heavy)",
    83: "Nursery Covers",
    # Water Pumps (cat 47)
    46: "Water Pumps",
    47: "Water Pump Parts",
    # Sprayers (cat 48)
    55: "Boom Sprayers",
    56: "Battery Sprayers",
    57: "Knapsack Sprayers",
    59: "HTP Sprayers",
    60: "HTP Sprayer Sets",
    61: "Portable Sprayers",
    78: "Sprayer Spare Parts",
    93: "Trolley Sprayers",
    94: "Li-Ion Battery Sprayers",
    # Earth Augers (cat 49)
    62: "Earth Augers (Small)",
    63: "Earth Augers (Large)",
    91: "Tree Planters (2-Man)",
    92: "Manual Tree Planters",
    104: "Earth Auger Spare Parts",
    105: "Drill Bits",
    # Chaff Cutters (cat 51)
    65: "Chaff Cutters",
    66: "Wood Chippers",
    # Seeders (cat 52)
    64: "Seeders",
    # Engines (cat 54)
    67: "Bare Engines",
    106: "2-Stroke Engines",
    107: "4-Stroke Engines",
    # Reapers (cat 55)
    68: "Petrol Reapers",
    90: "Reaper Attachments",
    98: "Tea Harvesters",
    # Chainsaws (cat 56)
    69: "Chainsaws (18\")",
    70: "Chainsaws (22\")",
    86: "Electric Chainsaws",
    87: "Electric Pole Saws",
    102: "Chainsaw Spare Parts",
    # Pressure Washers & Air Tools (cat 60)
    71: "Air Compressors (Oil-Based)",
    72: "Air Compressors (Oil-Free)",
    73: "High Pressure Washers (Light)",
    74: "High Pressure Washers (Heavy)",
    75: "Pressure Washers",
    76: "Pressure Washers (Brass)",
    82: "Foam Washers",
    88: "Electric Blowers",
    89: "Handheld Blowers",
    # Generators (cat 62)
    77: "Portable Generators",
    # Processing Equipment (cat 70)
    96: "Corn Threshers",
    97: "Rice Mills",
    99: "Micro Balers",
    100: "Harvesters",
    101: "Heavy Chaff Cutters",
    # Lighting (cat 71)
    95: "Torches & Flashlights",
    # Combos (cat 76)
    110: "Power Weeder Combos",
    111: "Power Weeder Combos (Pro)",
    112: "Multi-Tool Combos",
    113: "Brush Cutter Packages",
}


# ============================================================================
# Brand extraction
# ============================================================================

# Brands commonly found in product names/descriptions (ordered longest-first
# so "Fortune Agro" matches before "Fortune").
_KNOWN_BRANDS = [
    "Wellbeing Nutrition",
    "Fortune Agro",
    "Balwaan Shakti",
    "Balwaan",
    "Mitsuyama",
    "Mythsuyama",
    "Really",
    "Homaka",
    "Honda",
    "Jonathan",
    "Cornext",
    "Kisankraft",
]


def _extract_brand(name: str, description: str) -> str | None:
    """Try to identify brand from product name or description."""
    combined = f"{name} {description}"
    for brand in _KNOWN_BRANDS:
        if brand.lower() in combined.lower():
            return brand
    # Try "Brand - <value>" pattern in description
    match = re.search(r"Brand\s*[-:]\s*([A-Za-z][\w\s]*?)(?:_x000D_|\n|$)", description)
    if match:
        return match.group(1).strip()
    return None


# ============================================================================
# Excel loading
# ============================================================================


def _clean_description(raw: str | None) -> str:
    """Clean Excel description: strip carriage-return markers and extra whitespace."""
    if not raw:
        return ""
    text = raw.replace("_x000D_", "").replace("\r", "")
    # Collapse multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_products_from_excel(path: Path) -> list[dict]:
    """
    Read the Rural Equip product Excel and return a list of cleaned dicts
    ready for DB insertion.
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Sheet1"]

    products: list[dict] = []
    seen_ids: set[int] = set()

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
        row_id = row[0]
        if row_id is None or row_id in seen_ids:
            continue
        seen_ids.add(row_id)

        name = (row[1] or "").strip()
        if not name:
            continue

        price_original = Decimal(str(row[2] or 0))
        price_customer = Decimal(str(row[3] or 0))
        price_retailer = Decimal(str(row[4] or 0))
        description = _clean_description(row[5])
        category_id = row[6]
        subcategory_id = row[7]

        # Use customer price as the primary price; fall back to original.
        price = price_customer if price_customer > 0 else price_original

        brand = _extract_brand(name, description)
        category_name = CATEGORY_MAP.get(category_id, f"Unknown ({category_id})")
        subcategory_name = SUBCATEGORY_MAP.get(subcategory_id, f"Unknown ({subcategory_id})")

        # Build a richer description for embedding quality.
        full_description = description
        if not full_description:
            full_description = name
        full_description = (
            f"{name}. Category: {category_name} > {subcategory_name}. "
            f"{full_description}"
        )

        products.append(
            {
                "domain_slugs": [RURAL_DOMAIN],
                "sku": f"rural-{row_id}",
                "name": name,
                "brand": brand,
                "description": full_description,
                "price": price,
                "currency": "INR",
                "inventory_count": 100,
                "product_url": f"https://ruralequip.in/view_product.php?id={row_id}",
                "image_url": None,
                "attributes": {
                    "category": category_name,
                    "subcategory": subcategory_name,
                    "category_id": category_id,
                    "subcategory_id": subcategory_id,
                    "price_customer": float(price_customer),
                    "price_retailer": float(price_retailer),
                    "price_original": float(price_original),
                },
            }
        )

    wb.close()
    return products


# ============================================================================
# Database operations
# ============================================================================


async def seed_rural_products(products: list[dict]) -> int:
    """Insert rural products into the database. Returns count inserted."""
    async with async_session_factory() as session:
        # Remove only existing rural products (leave wellness data intact).
        delete_result = await session.execute(
            text("DELETE FROM products WHERE :slug = ANY(domain_slugs)"),
            {"slug": RURAL_DOMAIN},
        )
        if delete_result.rowcount:
            print(f"  Removed {delete_result.rowcount} existing rural products")
        await session.flush()

        count = 0
        for product_data in products:
            product = Product(
                tenant_id=RURAL_TENANT_ID,
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

            if count % 100 == 0:
                await session.flush()
                print(f"  Inserted {count} products...")

        await session.commit()
        return count


# ============================================================================
# JSON export (run locally where openpyxl is available)
# ============================================================================


def export_excel_to_json() -> None:
    """Convert the Excel file to JSON for use inside Docker."""
    import openpyxl  # noqa: F811 — only needed for this path

    excel_path = EXCEL_PATH.resolve()
    print(f"Loading rural products from {excel_path} ...")

    if not excel_path.exists():
        print(f"Error: Excel file not found at {excel_path}")
        print("Expected the cai-clients repo to be a sibling directory of curateai.")
        sys.exit(1)

    products = load_products_from_excel(excel_path)
    print(f"  Parsed {len(products)} products")

    # Decimal → float for JSON
    for p in products:
        if p["price"] is not None:
            p["price"] = float(p["price"])

    PRODUCTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(PRODUCTS_JSON, "w") as f:
        json.dump(products, f, indent=2, default=str)

    print(f"  Wrote {len(products)} products to {PRODUCTS_JSON}")


# ============================================================================
# JSON loading (works inside Docker without openpyxl)
# ============================================================================


def load_products_from_json() -> list[dict]:
    """Load pre-exported JSON product catalogue."""
    with open(PRODUCTS_JSON, encoding="utf-8") as f:
        raw: list[dict] = json.load(f)

    # Convert price back to Decimal for DB insertion
    for p in raw:
        if p.get("price") is not None:
            p["price"] = Decimal(str(p["price"]))

    return raw


# ============================================================================
# Main
# ============================================================================


def _print_category_breakdown(products: list[dict]) -> None:
    category_counts: dict[str, int] = {}
    for p in products:
        cat = p["attributes"]["category"]
        category_counts[cat] = category_counts.get(cat, 0) + 1

    print("\nProducts by category:")
    for cat, cnt in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {cnt}")


async def main() -> None:
    if "--export-json" in sys.argv:
        export_excel_to_json()
        return

    print(f"Loading rural products from {PRODUCTS_JSON} ...")

    if not PRODUCTS_JSON.exists():
        print(f"Error: {PRODUCTS_JSON} not found.")
        print("Run locally first:  python -m pipeline.seed_rural_products --export-json")
        sys.exit(1)

    products = load_products_from_json()
    print(f"  Loaded {len(products)} products")
    _print_category_breakdown(products)

    print("\nSeeding database...")
    count = await seed_rural_products(products)
    print(f"\nDone! Inserted {count} rural products.")
    print("\nNext step: generate embeddings with:")
    print("  docker compose exec app python -m app.services.generate_embeddings")


if __name__ == "__main__":
    asyncio.run(main())
