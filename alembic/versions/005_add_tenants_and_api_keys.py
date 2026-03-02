"""add tenants and api keys tables

Revision ID: 005_tenants_api_keys
Revises: f0796682ae3b
Create Date: 2026-03-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005_tenants_api_keys"
down_revision: Union[str, None] = "f0796682ae3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Seed tenant UUID — referenced by subsequent migrations
SEED_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # --- tenants table ---
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column(
            "enabled_domains",
            postgresql.ARRAY(sa.String(50)),
            server_default="{*}",
            nullable=False,
        ),
        sa.Column(
            "allowed_origins",
            postgresql.ARRAY(sa.String(500)),
            server_default="{*}",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "daily_bedrock_cost_cap_cents",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("500"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )

    # --- api_keys table ---
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("key_prefix", sa.String(8), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("allowed_ips", postgresql.ARRAY(sa.String(45)), nullable=True),
        sa.Column("rate_limit_rpm", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])

    # --- Seed default tenant ---
    op.execute(
        f"""
        INSERT INTO tenants (id, name, slug, enabled_domains, allowed_origins, is_active, daily_bedrock_cost_cap_cents)
        VALUES (
            '{SEED_TENANT_ID}',
            'Default Tenant',
            'default',
            ARRAY['*']::varchar(50)[],
            ARRAY['*']::varchar(500)[],
            true,
            500
        )
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("api_keys")
    op.drop_table("tenants")
