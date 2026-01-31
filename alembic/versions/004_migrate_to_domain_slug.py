"""migrate to domain_slug

Revision ID: 004_domain_slug
Revises: 003_journey_bundles
Create Date: 2026-01-30 00:00:00.000000

This migration replaces domain_id UUID foreign keys with domain_slug string columns
and removes the domains table as domain configuration is now managed via knowledge graphs.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_domain_slug'
down_revision = '003_journey_bundles'
branch_labels = None
depends_on = None


def upgrade():
    """
    Migrate from domain_id UUID FKs to domain_slug string columns.

    Steps:
    1. Add nullable domain_slug columns to products, chat_sessions, journey_bundles
    2. Migrate data (UUID → slug mapping)
    3. Make domain_slug NOT NULL
    4. Create indexes on domain_slug
    5. Drop FK constraints on domain_id
    6. Drop old columns: domain_id, current_domain_id
    7. Drop domains table
    """

    # Step 1: Add nullable domain_slug columns
    op.add_column('products', sa.Column('domain_slug', sa.String(50), nullable=True))
    op.add_column('chat_sessions', sa.Column('current_domain_slug', sa.String(50), nullable=True))
    op.add_column('journey_bundles', sa.Column('domain_slug', sa.String(50), nullable=True))

    # Step 2: Migrate data (UUID → slug mapping)
    # Map domain UUIDs to their slugs
    op.execute("""
        UPDATE products
        SET domain_slug = (SELECT slug FROM domains WHERE id = products.domain_id)
    """)

    op.execute("""
        UPDATE chat_sessions
        SET current_domain_slug = (SELECT slug FROM domains WHERE id = chat_sessions.current_domain_id)
        WHERE current_domain_id IS NOT NULL
    """)

    op.execute("""
        UPDATE journey_bundles
        SET domain_slug = (SELECT slug FROM domains WHERE id = journey_bundles.domain_id)
    """)

    # Step 3: Make domain_slug NOT NULL (except current_domain_slug which can be NULL)
    op.alter_column('products', 'domain_slug', nullable=False)
    op.alter_column('journey_bundles', 'domain_slug', nullable=False)
    # current_domain_slug stays nullable

    # Step 4: Create indexes on domain_slug
    op.create_index('ix_products_domain_slug', 'products', ['domain_slug'])
    op.create_index('ix_journey_bundles_domain_slug', 'journey_bundles', ['domain_slug'])

    # Step 5: Drop FK constraints on domain_id
    # Products
    op.drop_constraint('products_domain_id_fkey', 'products', type_='foreignkey')
    op.drop_index('idx_products_domain', table_name='products')

    # Chat Sessions
    op.drop_constraint('chat_sessions_current_domain_id_fkey', 'chat_sessions', type_='foreignkey')

    # Journey Bundles
    op.drop_constraint('journey_bundles_domain_id_fkey', 'journey_bundles', type_='foreignkey')
    op.drop_index('idx_journey_bundles_domain', table_name='journey_bundles')

    # Drop old unique constraint on journey_bundles
    op.drop_constraint('uq_domain_journey', 'journey_bundles', type_='unique')

    # Step 6: Drop old columns
    op.drop_column('products', 'domain_id')
    op.drop_column('chat_sessions', 'current_domain_id')
    op.drop_column('journey_bundles', 'domain_id')

    # Create new unique constraint with domain_slug
    op.create_unique_constraint(
        'uq_journey_bundle_domain_journey',
        'journey_bundles',
        ['domain_slug', 'journey_id']
    )

    # Step 7: Drop domains table
    op.drop_table('domains')


def downgrade():
    """
    Restore domain_id columns and domains table.

    WARNING: This downgrade requires the domains table to be recreated
    with the same UUIDs. You should restore from a backup instead.
    """

    # Recreate domains table
    op.create_table(
        'domains',
        sa.Column('id', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('slug', sa.String(50), nullable=False),
        sa.Column('parent_domain_id', postgresql.UUID(), nullable=True),
        sa.Column('config', postgresql.JSONB(), nullable=False),
        sa.Column('system_persona', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('slug'),
        sa.ForeignKeyConstraint(['parent_domain_id'], ['domains.id'])
    )

    # Add back domain_id columns
    op.add_column('products', sa.Column('domain_id', postgresql.UUID(), nullable=True))
    op.add_column('chat_sessions', sa.Column('current_domain_id', postgresql.UUID(), nullable=True))
    op.add_column('journey_bundles', sa.Column('domain_id', postgresql.UUID(), nullable=True))

    # Restore data (slug → UUID mapping)
    # NOTE: This requires domains table to have matching slugs
    op.execute("""
        UPDATE products
        SET domain_id = (SELECT id FROM domains WHERE slug = products.domain_slug)
    """)

    op.execute("""
        UPDATE chat_sessions
        SET current_domain_id = (SELECT id FROM domains WHERE slug = chat_sessions.current_domain_slug)
        WHERE current_domain_slug IS NOT NULL
    """)

    op.execute("""
        UPDATE journey_bundles
        SET domain_id = (SELECT id FROM domains WHERE slug = journey_bundles.domain_slug)
    """)

    # Make domain_id NOT NULL
    op.alter_column('products', 'domain_id', nullable=False)
    op.alter_column('journey_bundles', 'domain_id', nullable=False)

    # Recreate FK constraints
    op.create_foreign_key('products_domain_id_fkey', 'products', 'domains', ['domain_id'], ['id'])
    op.create_foreign_key('chat_sessions_current_domain_id_fkey', 'chat_sessions', 'domains', ['current_domain_id'], ['id'])
    op.create_foreign_key('journey_bundles_domain_id_fkey', 'journey_bundles', 'domains', ['domain_id'], ['id'], ondelete='CASCADE')

    # Recreate indexes
    op.create_index('idx_products_domain', 'products', ['domain_id'])
    op.create_index('idx_journey_bundles_domain', 'journey_bundles', ['domain_id'])

    # Drop new unique constraint
    op.drop_constraint('uq_journey_bundle_domain_journey', 'journey_bundles', type_='unique')

    # Recreate old unique constraint
    op.create_unique_constraint('uq_domain_journey', 'journey_bundles', ['domain_id', 'journey_id'])

    # Drop domain_slug columns and indexes
    op.drop_index('ix_journey_bundles_domain_slug', table_name='journey_bundles')
    op.drop_index('ix_products_domain_slug', table_name='products')

    op.drop_column('products', 'domain_slug')
    op.drop_column('chat_sessions', 'current_domain_slug')
    op.drop_column('journey_bundles', 'domain_slug')
