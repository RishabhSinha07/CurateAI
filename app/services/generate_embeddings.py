"""
Script to generate embeddings for all products.

Run with: python -m app.services.generate_embeddings
"""

import asyncio

from sqlalchemy import select, update

from app.db.models import Product
from app.db.session import async_session_factory
from app.services.embeddings import generate_embedding_async


async def generate_product_embeddings() -> None:
    """Generate embeddings for all products that don't have one."""
    async with async_session_factory() as session:
        # Get products without embeddings
        result = await session.execute(
            select(Product).where(Product.description_embedding.is_(None))
        )
        products = result.scalars().all()

        if not products:
            print("All products already have embeddings.")
            return

        print(f"Generating embeddings for {len(products)} products...")

        for i, product in enumerate(products, 1):
            # Create text to embed (name + description + key attributes)
            text_parts = [product.name]
            if product.description:
                text_parts.append(product.description)
            if product.brand:
                text_parts.append(f"Brand: {product.brand}")

            # Add relevant attributes
            attrs = product.attributes or {}
            if "active_ingredients" in attrs:
                text_parts.append(f"Ingredients: {', '.join(attrs['active_ingredients'])}")
            if "skin_type" in attrs:
                skin_types = attrs["skin_type"]
                if isinstance(skin_types, list):
                    text_parts.append(f"For skin types: {', '.join(skin_types)}")
            if "skin_concern" in attrs:
                concerns = attrs["skin_concern"]
                if isinstance(concerns, list):
                    text_parts.append(f"Addresses: {', '.join(concerns)}")

            text_to_embed = " | ".join(text_parts)

            try:
                print(f"  [{i}/{len(products)}] {product.name}...", end=" ", flush=True)
                embedding = await generate_embedding_async(text_to_embed)

                # Update product with embedding
                await session.execute(
                    update(Product)
                    .where(Product.id == product.id)
                    .values(description_embedding=embedding)
                )
                print("✓")

            except Exception as e:
                print(f"✗ Error: {e}")
                continue

        await session.commit()
        print(f"\nDone! Generated embeddings for {len(products)} products.")


async def check_embedding_status() -> None:
    """Check how many products have embeddings."""
    async with async_session_factory() as session:
        # Count products with and without embeddings
        result_with = await session.execute(
            select(Product).where(Product.description_embedding.is_not(None))
        )
        result_without = await session.execute(
            select(Product).where(Product.description_embedding.is_(None))
        )

        with_embeddings = len(result_with.scalars().all())
        without_embeddings = len(result_without.scalars().all())

        print(f"Products with embeddings: {with_embeddings}")
        print(f"Products without embeddings: {without_embeddings}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        asyncio.run(check_embedding_status())
    else:
        asyncio.run(generate_product_embeddings())
