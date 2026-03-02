"""
CLI script for creating tenants and API keys.

Usage:
    python -m scripts.create_tenant --name "Acme" --slug "acme" --domains wellness,skin_health_radiance
    python -m scripts.create_tenant --name "HealthCo" --slug "healthco"  # All domains enabled

Outputs the API key once — store it securely.
"""

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import select

# Ensure the app module is importable
sys.path.insert(0, ".")

from app.db.session import async_session_factory
from app.db.models import Tenant
from app.db.repositories.tenant import TenantRepository


async def create_tenant(
    name: str,
    slug: str,
    domains: list[str] | None = None,
    origins: list[str] | None = None,
) -> None:
    if async_session_factory is None:
        print("ERROR: DATABASE_URL not configured. Set it in .env or environment.")
        sys.exit(1)

    async with async_session_factory() as session:
        # Check for existing tenant
        existing = await session.execute(
            select(Tenant).where(Tenant.slug == slug)
        )
        if existing.scalar_one_or_none():
            print(f"ERROR: Tenant with slug '{slug}' already exists.")
            sys.exit(1)

        # Create tenant
        tenant = Tenant(
            name=name,
            slug=slug,
            enabled_domains=domains or ["*"],
            allowed_origins=origins or ["*"],
        )
        session.add(tenant)
        await session.flush()

        # Create API key
        repo = TenantRepository(session)
        api_key, raw_key = await repo.create_api_key(
            tenant_id=tenant.id,
            label="Initial key",
        )

        await session.commit()

        print(f"\nTenant created successfully!")
        print(f"  Name:     {name}")
        print(f"  Slug:     {slug}")
        print(f"  ID:       {tenant.id}")
        print(f"  Domains:  {tenant.enabled_domains}")
        print(f"  Origins:  {tenant.allowed_origins}")
        print(f"\nAPI Key (store this — it will NOT be shown again):")
        print(f"  {raw_key}")
        print(f"  Prefix:   {api_key.key_prefix}")
        print(f"  RPM:      {api_key.rate_limit_rpm}")


def main():
    parser = argparse.ArgumentParser(description="Create a CurateAI tenant")
    parser.add_argument("--name", required=True, help="Tenant display name")
    parser.add_argument("--slug", required=True, help="Tenant slug (URL-safe, unique)")
    parser.add_argument(
        "--domains",
        default=None,
        help="Comma-separated enabled domains (default: all). E.g., wellness,skin_health_radiance",
    )
    parser.add_argument(
        "--origins",
        default=None,
        help="Comma-separated allowed CORS origins (default: *). E.g., https://app.example.com",
    )

    args = parser.parse_args()

    domains = args.domains.split(",") if args.domains else None
    origins = args.origins.split(",") if args.origins else None

    asyncio.run(create_tenant(args.name, args.slug, domains, origins))


if __name__ == "__main__":
    main()
