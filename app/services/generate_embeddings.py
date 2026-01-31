"""
Script to generate embeddings for all products.

Run with: python -m app.services.generate_embeddings
"""

import asyncio

from sqlalchemy import select, update

from app.db.models import Product
from app.db.session import async_session_factory
from app.services.embeddings import generate_embedding_async


async def generate_product_embeddings(regenerate: bool = False) -> None:
    """
    Generate embeddings for products.

    Args:
        regenerate: If True, regenerate embeddings for all products (even those with existing embeddings)
    """
    async with async_session_factory() as session:
        # Get products based on regenerate flag
        if regenerate:
            result = await session.execute(select(Product))
            products = result.scalars().all()
            print(f"Regenerating embeddings for all {len(products)} products...")
        else:
            result = await session.execute(
                select(Product).where(Product.description_embedding.is_(None))
            )
            products = result.scalars().all()

            if not products:
                print("All products already have embeddings.")
                print("Use --regenerate to regenerate embeddings for all products.")
                return

            print(f"Generating embeddings for {len(products)} new products...")

        for i, product in enumerate(products, 1):
            # Create text to embed (name + description + key attributes)
            text_parts = [product.name]
            if product.description:
                text_parts.append(product.description)
            if product.brand:
                text_parts.append(f"Brand: {product.brand}")

            # Add relevant attributes
            attrs = product.attributes or {}

            # Ingredients (critical for matching)
            if "ingredients" in attrs:
                ingredients = attrs["ingredients"]
                if isinstance(ingredients, list):
                    text_parts.append(f"Ingredients: {', '.join(ingredients)}")

            # Health goals/problems (for both skin and hair)
            if "health_goals" in attrs:
                goals = attrs["health_goals"]
                if isinstance(goals, list):
                    text_parts.append(f"Helps with: {', '.join(goals)}")

            # Skin-specific attributes
            if "skin_type" in attrs:
                skin_types = attrs["skin_type"]
                if isinstance(skin_types, list):
                    text_parts.append(f"For skin types: {', '.join(skin_types)}")
                elif skin_types:
                    text_parts.append(f"For skin type: {skin_types}")

            if "skin_concern" in attrs:
                concerns = attrs["skin_concern"]
                if isinstance(concerns, list):
                    text_parts.append(f"Addresses skin concerns: {', '.join(concerns)}")
                elif concerns:
                    text_parts.append(f"Addresses: {concerns}")

            # Hair-specific attributes
            if "hair_type" in attrs:
                hair_types = attrs["hair_type"]
                if isinstance(hair_types, list):
                    text_parts.append(f"For hair types: {', '.join(hair_types)}")
                elif hair_types:
                    text_parts.append(f"For hair type: {hair_types}")

            if "scalp_condition" in attrs:
                scalp = attrs["scalp_condition"]
                text_parts.append(f"Scalp condition: {scalp}")

            # Gender-specific (for targeted products)
            if "gender_specific" in attrs:
                gender = attrs["gender_specific"]
                if gender and gender != "all":
                    text_parts.append(f"For {gender}")

            # Category (helps with domain identification)
            if "category" in attrs:
                category = attrs["category"]
                text_parts.append(f"Category: {category}")

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

    if len(sys.argv) > 1:
        if sys.argv[1] == "--status":
            asyncio.run(check_embedding_status())
        elif sys.argv[1] == "--regenerate":
            print("⚠️  This will regenerate embeddings for ALL products (may take time and cost)")
            confirm = input("Continue? (y/n): ")
            if confirm.lower() == 'y':
                asyncio.run(generate_product_embeddings(regenerate=True))
            else:
                print("Cancelled.")
        else:
            print("Usage:")
            print("  python -m app.services.generate_embeddings              # Generate for new products only")
            print("  python -m app.services.generate_embeddings --status     # Check embedding status")
            print("  python -m app.services.generate_embeddings --regenerate # Regenerate all embeddings")
    else:
        asyncio.run(generate_product_embeddings())
