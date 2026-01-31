"""change_domain_slug_to_array

Revision ID: f0796682ae3b
Revises: 004_domain_slug
Create Date: 2026-01-31 20:52:53.067867

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0796682ae3b'
down_revision: Union[str, None] = '004_domain_slug'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Migrate domain_slug from single VARCHAR to array of VARCHARs.

    Steps:
    1. Add new domain_slugs column as array
    2. Migrate existing domain_slug data to domain_slugs array
    3. Drop old domain_slug column
    4. Update index
    """
    # Step 1: Add new column
    op.add_column(
        'products',
        sa.Column('domain_slugs', sa.ARRAY(sa.String(50)), nullable=True)
    )

    # Step 2: Migrate data - convert single domain_slug to array
    op.execute("""
        UPDATE products
        SET domain_slugs = ARRAY[domain_slug]
        WHERE domain_slug IS NOT NULL
    """)

    # Step 3: Make domain_slugs non-nullable and set default
    op.alter_column('products', 'domain_slugs', nullable=False)

    # Step 4: Drop old column and its index
    op.drop_index('ix_products_domain_slug', table_name='products')
    op.drop_column('products', 'domain_slug')

    # Step 5: Create GIN index for array column (better for array containment queries)
    op.execute("""
        CREATE INDEX ix_products_domain_slugs
        ON products USING GIN (domain_slugs)
    """)


def downgrade() -> None:
    """
    Rollback: Convert domain_slugs array back to single domain_slug.

    WARNING: If products have multiple domains, only the first will be kept!
    """
    # Step 1: Add back domain_slug column
    op.add_column(
        'products',
        sa.Column('domain_slug', sa.String(50), nullable=True)
    )

    # Step 2: Migrate data - take first element of array
    op.execute("""
        UPDATE products
        SET domain_slug = domain_slugs[1]
        WHERE domain_slugs IS NOT NULL AND array_length(domain_slugs, 1) > 0
    """)

    # Step 3: Make domain_slug non-nullable
    op.alter_column('products', 'domain_slug', nullable=False)

    # Step 4: Drop array column and its index
    op.drop_index('ix_products_domain_slugs', table_name='products')
    op.drop_column('products', 'domain_slugs')

    # Step 5: Recreate btree index
    op.create_index('ix_products_domain_slug', 'products', ['domain_slug'])
