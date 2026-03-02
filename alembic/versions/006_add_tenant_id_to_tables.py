"""add tenant_id to existing tables

Revision ID: 006_add_tenant_id
Revises: 005_tenants_api_keys
Create Date: 2026-03-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "006_add_tenant_id"
down_revision: Union[str, None] = "005_tenants_api_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEED_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # --- Phase A: Add nullable tenant_id columns ---
    for table in ("products", "chat_sessions", "chat_messages", "journey_bundles"):
        op.add_column(table, sa.Column("tenant_id", sa.Uuid(), nullable=True))

    # --- Phase B: Backfill all existing rows with the seed tenant ---
    for table in ("products", "chat_sessions", "chat_messages", "journey_bundles"):
        op.execute(
            f"UPDATE {table} SET tenant_id = '{SEED_TENANT_ID}' WHERE tenant_id IS NULL"
        )

    # --- Phase C: Set NOT NULL + FK + indexes ---
    for table in ("products", "chat_sessions", "chat_messages", "journey_bundles"):
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_tenant_id",
            table,
            "tenants",
            ["tenant_id"],
            ["id"],
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])


def downgrade() -> None:
    for table in ("journey_bundles", "chat_messages", "chat_sessions", "products"):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant_id", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")
