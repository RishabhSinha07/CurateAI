"""add tenant.vertical column

Revision ID: 009_tenant_vertical
Revises: 008_admin_users
Create Date: 2026-05-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "009_tenant_vertical"
down_revision: Union[str, None] = "008_admin_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "vertical",
            sa.String(length=50),
            nullable=False,
            server_default="commerce",
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "vertical")
