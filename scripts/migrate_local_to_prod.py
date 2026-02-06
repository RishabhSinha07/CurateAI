#!/usr/bin/env python3
"""
Migrate products from local Docker PostgreSQL to production Neon database.

This script:
1. Exports all products from local Docker DB
2. Imports them into production Neon DB
3. Preserves all data including embeddings

Usage:
    python scripts/migrate_local_to_prod.py
"""
import asyncio
import asyncpg
from datetime import datetime

# Database URLs
LOCAL_DB = "postgresql://postgres:postgres@localhost:5432/curateai"
PROD_DB = "postgresql://neondb_owner:npg_63rZkjATYsiQ@ep-green-moon-aia3mla2-pooler.c-4.us-east-1.aws.neon.tech/neondb"


async def migrate_products():
    """Migrate products from local to production database."""

    print("🔄 Starting product migration...")
    print(f"📤 Source: Local Docker PostgreSQL")
    print(f"📥 Target: Production Neon PostgreSQL\n")

    # Connect to both databases
    print("🔌 Connecting to databases...")
    local_conn = await asyncpg.connect(LOCAL_DB)
    prod_conn = await asyncpg.connect(PROD_DB)

    try:
        # 1. Count products in local DB
        local_count = await local_conn.fetchval("SELECT COUNT(*) FROM products")
        print(f"✅ Found {local_count} products in local database\n")

        # 2. Check if production DB has products
        prod_count = await prod_conn.fetchval("SELECT COUNT(*) FROM products")
        print(f"📊 Production database currently has {prod_count} products")

        if prod_count > 0:
            response = input(f"\n⚠️  Production DB has {prod_count} products. Delete them first? (yes/no): ")
            if response.lower() == 'yes':
                await prod_conn.execute("TRUNCATE TABLE products CASCADE")
                print("🗑️  Cleared production database")
            else:
                print("❌ Migration cancelled")
                return

        # 3. Export products from local DB
        print(f"\n📤 Exporting {local_count} products from local database...")
        products = await local_conn.fetch("""
            SELECT
                id,
                domain_slugs,
                sku,
                name,
                brand,
                description,
                price,
                currency,
                inventory_count,
                product_url,
                image_url,
                attributes,
                description_embedding,
                is_active,
                created_at,
                updated_at
            FROM products
            ORDER BY created_at
        """)
        print(f"✅ Exported {len(products)} products")

        # 4. Import products to production DB
        print(f"\n📥 Importing products to production database...")

        inserted = 0
        errors = 0

        for product in products:
            try:
                await prod_conn.execute("""
                    INSERT INTO products (
                        id,
                        domain_slugs,
                        sku,
                        name,
                        brand,
                        description,
                        price,
                        currency,
                        inventory_count,
                        product_url,
                        image_url,
                        attributes,
                        description_embedding,
                        is_active,
                        created_at,
                        updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                """,
                    product['id'],
                    product['domain_slugs'],
                    product['sku'],
                    product['name'],
                    product['brand'],
                    product['description'],
                    product['price'],
                    product['currency'],
                    product['inventory_count'],
                    product['product_url'],
                    product['image_url'],
                    product['attributes'],
                    product['description_embedding'],
                    product['is_active'],
                    product['created_at'],
                    product['updated_at']
                )
                inserted += 1
                if inserted % 10 == 0:
                    print(f"   ✓ Inserted {inserted}/{len(products)} products...")
            except Exception as e:
                errors += 1
                print(f"   ✗ Error inserting {product['name']}: {e}")

        # 5. Verify migration
        print(f"\n📊 Migration Summary:")
        print(f"   ✅ Successfully inserted: {inserted} products")
        if errors > 0:
            print(f"   ❌ Errors: {errors} products")

        final_count = await prod_conn.fetchval("SELECT COUNT(*) FROM products")
        print(f"\n✅ Production database now has {final_count} products")

        # 6. Show sample products
        print(f"\n📦 Sample products in production:")
        samples = await prod_conn.fetch("""
            SELECT name, brand, domain_slugs, price
            FROM products
            LIMIT 5
        """)
        for sample in samples:
            print(f"   • {sample['name']} ({sample['brand']}) - {sample['domain_slugs']} - ₹{sample['price']}")

        print(f"\n🎉 Migration complete!")

    finally:
        await local_conn.close()
        await prod_conn.close()
        print("\n🔌 Database connections closed")


if __name__ == "__main__":
    asyncio.run(migrate_products())
