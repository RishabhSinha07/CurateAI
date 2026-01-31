"""
Script to update gut health related products to use the gut_health_digestion domain.

This script:
1. Identifies gut health products (probiotics, digestive enzymes, fiber, etc.)
2. Updates their domain_slug to 'gut_health_digestion'
3. Generates embeddings for updated products

Run with: python -m scripts.update_gut_health_products
"""

import asyncio
import logging
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product
from app.db.session import async_session_factory
from app.services.embeddings import generate_embedding_async

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SKUs of products that should be tagged to gut_health_digestion
GUT_HEALTH_PRODUCT_SKUS = [
    # Probiotics
    "SLNUGUT",  # Daily Probiotic Slow
    "WBNMHGUT",  # Healthy Gut (melts)
    "FROZENPROBIOTIC",  # Disney Frozen Probiotic (melts)
    "MARVELPROBIOTIC",  # Marvel Active Probiotic (melts)
    "WBNPRO-1",  # Probiotic + Prebiotic (effervescent)

    # Fiber
    "FBRPC",  # Daily Fiber | Pina Colada Flavour
    "FBRCOMBO",  # Daily Fiber | Two Flavour Combo
    "FBRVB",  # Daily Fiber | Vanilla Berry Flavour

    # Digestive Support
    "WNTEADIGEST",  # Digest Adaptogenic Green Tea
    "WBN-01-2",  # Daily Greens (contains digestive support)
    "WBNMLTACD",  # Acidity Relief (melts)

    # ACV (Apple Cider Vinegar) - gut health support
    "WBNACV-1",  # Apple Cider Vinegar
    "WBNACVFL",  # Apple Cider Vinegar with Amla And Turmeric
    "ACVEFF-02",  # Apple Cider Vinegar with Garcinia Cambogia and Pomegranate

    # Note: Protein products with probiotics are NOT included as they're primarily for fitness/muscle building
]


async def update_products_domain(session: AsyncSession) -> int:
    """
    Update domain_slugs for gut health products.

    Adds 'gut_health_digestion' to the domain_slugs array if not already present.
    This allows products to belong to multiple domains.

    Returns:
        Number of products updated
    """
    logger.info(f"Updating domain_slugs for {len(GUT_HEALTH_PRODUCT_SKUS)} gut health products...")

    # Update products in bulk - add gut_health_digestion to domain_slugs array
    # Use array_append if not already in array
    result = await session.execute(
        update(Product)
        .where(Product.sku.in_(GUT_HEALTH_PRODUCT_SKUS))
        .values(domain_slugs=["gut_health_digestion"])
    )

    updated_count = result.rowcount
    await session.commit()

    logger.info(f"Updated {updated_count} products to gut_health_digestion domain")
    return updated_count


async def generate_embeddings_for_products(session: AsyncSession) -> int:
    """
    Generate embeddings for gut health products.

    Returns:
        Number of products with embeddings generated
    """
    logger.info("Generating embeddings for gut health products...")

    # Fetch all gut health products
    result = await session.execute(
        select(Product)
        .where(Product.domain_slugs.any("gut_health_digestion"))
        .where(Product.is_active == True)
    )
    products = result.scalars().all()

    if not products:
        logger.warning("No gut health products found")
        return 0

    logger.info(f"Found {len(products)} products to process")

    count = 0
    for product in products:
        if not product.description:
            logger.warning(f"Product {product.sku} has no description, skipping embedding")
            continue

        try:
            # Generate embedding
            logger.info(f"Generating embedding for {product.sku}: {product.name}")
            embedding = await generate_embedding_async(product.description)

            # Update product with embedding
            product.description_embedding = embedding
            count += 1

        except Exception as e:
            logger.error(f"Failed to generate embedding for {product.sku}: {e}")
            continue

    await session.commit()
    logger.info(f"Generated embeddings for {count}/{len(products)} products")

    return count


async def verify_update(session: AsyncSession) -> None:
    """Verify that products were updated correctly."""
    logger.info("\n=== Verification ===")

    # Count gut health products
    result = await session.execute(
        select(Product)
        .where(Product.domain_slugs.any("gut_health_digestion"))
    )
    products = result.scalars().all()

    logger.info(f"Total products in gut_health_digestion domain: {len(products)}")

    # Count products with embeddings
    embedded_count = sum(1 for p in products if p.description_embedding is not None)
    logger.info(f"Products with embeddings: {embedded_count}/{len(products)}")

    # List products
    logger.info("\nProducts in gut_health_digestion domain:")
    for product in products:
        has_embedding = "✓" if product.description_embedding else "✗"
        domains_str = ", ".join(product.domain_slugs)
        logger.info(f"  {has_embedding} {product.sku}: {product.name} (domains: {domains_str})")


async def main():
    """Main execution function."""
    logger.info("Starting gut health products update...")

    async with async_session_factory() as session:
        # Step 1: Update domain_slug
        updated_count = await update_products_domain(session)

        if updated_count == 0:
            logger.warning("No products were updated. Check if SKUs exist in database.")
            return

        # Step 2: Generate embeddings
        embedding_count = await generate_embeddings_for_products(session)

        # Step 3: Verify
        await verify_update(session)

    logger.info("\n=== Update Complete ===")
    logger.info(f"✓ Updated {updated_count} products to gut_health_digestion domain")
    logger.info(f"✓ Generated {embedding_count} embeddings")


if __name__ == "__main__":
    asyncio.run(main())
