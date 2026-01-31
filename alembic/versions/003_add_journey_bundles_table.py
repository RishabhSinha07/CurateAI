"""add journey bundles table

Revision ID: 003_journey_bundles
Revises: 002_embedding_dim
Create Date: 2026-01-25 21:50:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003_journey_bundles'
down_revision = '002_embedding_dim'
branch_labels = None
depends_on = None


def upgrade():
    # Create journey_bundles table
    op.create_table(
        'journey_bundles',
        sa.Column('id', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('domain_id', postgresql.UUID(), nullable=False),
        sa.Column('journey_id', sa.String(100), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('keywords', postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column('product_categories', postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column('product_tags', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('guidance_templates', postgresql.JSONB(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('domain_id', 'journey_id', name='uq_domain_journey')
    )
    
    # Create indexes
    op.create_index('idx_journey_bundles_domain', 'journey_bundles', ['domain_id'])
    op.create_index('idx_journey_bundles_keywords', 'journey_bundles', ['keywords'], postgresql_using='gin')


def downgrade():
    op.drop_index('idx_journey_bundles_keywords', table_name='journey_bundles')
    op.drop_index('idx_journey_bundles_domain', table_name='journey_bundles')
    op.drop_table('journey_bundles')
