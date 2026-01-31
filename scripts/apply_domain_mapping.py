"""
Script to apply multi-domain mapping to products.

This script reads the product_domain_mapping.yaml file and updates products
to belong to multiple domains based on their benefits and ingredients.

Run with: python -m scripts.apply_domain_mapping
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List

import yaml
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product
from app.db.session import async_session_factory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAPPING_FILE = Path(__file__).resolve().parents[1] / "app" / "knowledge" / "product_domain_mapping.yaml"


def load_domain_mapping() -> Dict[str, List[str]]:
    """
    Load product-domain mapping from YAML file.

    Returns:
        Dictionary mapping SKU to list of domain slugs
    """
    if not MAPPING_FILE.exists():
        raise FileNotFoundError(f"Mapping file not found: {MAPPING_FILE}")

    logger.info(f"Loading domain mapping from {MAPPING_FILE}")

    with open(MAPPING_FILE, 'r') as f:
        mapping = yaml.safe_load(f)

    # Filter out None values and comments
    clean_mapping = {
        sku: domains
        for sku, domains in mapping.items()
        if domains and isinstance(domains, list) and sku and not sku.startswith('#')
    }

    logger.info(f"Loaded mapping for {len(clean_mapping)} products")
    return clean_mapping


async def apply_mapping(session: AsyncSession, mapping: Dict[str, List[str]]) -> Dict[str, int]:
    """
    Apply domain mapping to products.

    Args:
        session: Database session
        mapping: Dictionary mapping SKU to domain slugs

    Returns:
        Statistics dictionary
    """
    stats = {
        "total_products_in_mapping": len(mapping),
        "updated": 0,
        "not_found": 0,
        "errors": 0,
    }

    for sku, domain_slugs in mapping.items():
        try:
            # Fetch product
            result = await session.execute(
                select(Product).where(Product.sku == sku)
            )
            product = result.scalar_one_or_none()

            if not product:
                logger.warning(f"Product not found: {sku}")
                stats["not_found"] += 1
                continue

            # Update domain_slugs
            old_domains = product.domain_slugs
            product.domain_slugs = domain_slugs

            logger.info(
                f"Updated {sku}: {product.name}\n"
                f"  Old domains: {old_domains}\n"
                f"  New domains: {domain_slugs}"
            )

            stats["updated"] += 1

        except Exception as e:
            logger.error(f"Error updating {sku}: {e}")
            stats["errors"] += 1

    await session.commit()
    return stats


async def verify_mapping(session: AsyncSession) -> None:
    """Verify that products have correct domains."""
    logger.info("\n=== Verification ===")

    # Get all products with multiple domains
    result = await session.execute(
        select(Product)
        .where(Product.domain_slugs != None)
    )
    products = result.scalars().all()

    # Count products by number of domains
    domain_counts = {}
    for product in products:
        num_domains = len(product.domain_slugs)
        domain_counts[num_domains] = domain_counts.get(num_domains, 0) + 1

    logger.info("\nProducts by number of domains:")
    for num, count in sorted(domain_counts.items()):
        logger.info(f"  {num} domain(s): {count} products")

    # List products with multiple domains
    multi_domain_products = [p for p in products if len(p.domain_slugs) > 1]

    logger.info(f"\nProducts in multiple domains ({len(multi_domain_products)}):")
    for product in multi_domain_products:
        domains_str = ", ".join(product.domain_slugs)
        primary = product.domain_slugs[0]
        secondary = product.domain_slugs[1:] if len(product.domain_slugs) > 1 else []
        logger.info(
            f"  {product.sku}: {product.name}\n"
            f"    Primary: {primary}\n"
            f"    Secondary: {', '.join(secondary) if secondary else 'None'}"
        )

    # Count products per domain
    logger.info("\nProducts per domain:")
    domain_product_counts = {}
    for product in products:
        for domain in product.domain_slugs:
            domain_product_counts[domain] = domain_product_counts.get(domain, 0) + 1

    for domain, count in sorted(domain_product_counts.items()):
        logger.info(f"  {domain}: {count} products")


async def main():
    """Main execution function."""
    logger.info("Starting multi-domain mapping application...")

    try:
        # Load mapping
        mapping = load_domain_mapping()

        async with async_session_factory() as session:
            # Apply mapping
            stats = await apply_mapping(session, mapping)

            # Print statistics
            logger.info("\n=== Statistics ===")
            logger.info(f"Total products in mapping: {stats['total_products_in_mapping']}")
            logger.info(f"Successfully updated: {stats['updated']}")
            logger.info(f"Not found: {stats['not_found']}")
            logger.info(f"Errors: {stats['errors']}")

            # Verify
            await verify_mapping(session)

        logger.info("\n=== Complete ===")
        logger.info(f"✓ Updated {stats['updated']} products with multi-domain mapping")

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
