"""Change embedding dimension from 1536 to 1024 for Titan v2

Revision ID: 002_embedding_dim
Revises: 001_initial
Create Date: 2025-01-23

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_embedding_dim"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the old index if it exists (may not exist if no data was indexed)
    op.execute("DROP INDEX IF EXISTS idx_products_embedding")

    # Change column type from vector(1536) to vector(1024)
    op.execute("ALTER TABLE products ALTER COLUMN description_embedding TYPE vector(1024)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_products_embedding")
    op.execute("ALTER TABLE products ALTER COLUMN description_embedding TYPE vector(1536)")
