"""
CLI script for registering admin users.

Creates an admin user with email + password, mapped to a tenant.

Usage:
    python -m scripts.create_admin_user \
        --email admin@company.com \
        --password secretpass123 \
        --tenant-slug acme \
        --role owner
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

# Ensure the app module is importable
sys.path.insert(0, ".")

from app.db.session import async_session_factory
from app.db.models import AdminUser, Tenant
from app.api.middleware.cognito import hash_password


async def create_admin_user(
    email: str,
    password: str,
    tenant_slug: str,
    role: str = "owner",
) -> None:
    if async_session_factory is None:
        print("ERROR: DATABASE_URL not configured. Set it in .env or environment.")
        sys.exit(1)

    async with async_session_factory() as session:
        # Look up tenant by slug
        result = await session.execute(
            select(Tenant).where(Tenant.slug == tenant_slug)
        )
        tenant = result.scalar_one_or_none()
        if tenant is None:
            print(f"ERROR: Tenant with slug '{tenant_slug}' not found.")
            sys.exit(1)

        # Check for existing admin with same email
        result = await session.execute(
            select(AdminUser).where(AdminUser.email == email)
        )
        if result.scalar_one_or_none():
            print(f"ERROR: Admin user with email '{email}' already exists.")
            sys.exit(1)

        # Create admin user
        admin = AdminUser(
            tenant_id=tenant.id,
            email=email,
            password_hash=hash_password(password),
            role=role,
        )
        session.add(admin)
        await session.commit()

        print(f"\nAdmin user created successfully!")
        print(f"  ID:        {admin.id}")
        print(f"  Email:     {email}")
        print(f"  Role:      {role}")
        print(f"  Tenant:    {tenant.name} ({tenant.slug})")
        print(f"  Tenant ID: {tenant.id}")
        print(f"\nLogin:")
        print(f"  POST /admin/dashboard/login")
        print(f'  {{"email": "{email}", "password": "***"}}')


def main():
    parser = argparse.ArgumentParser(description="Register a CurateAI admin user")
    parser.add_argument("--email", required=True, help="Admin email address")
    parser.add_argument("--password", required=True, help="Admin password")
    parser.add_argument("--tenant-slug", required=True, help="Tenant slug to assign admin to")
    parser.add_argument(
        "--role",
        default="owner",
        help="Admin role (default: owner). Options: owner, viewer",
    )

    args = parser.parse_args()
    asyncio.run(create_admin_user(args.email, args.password, args.tenant_slug, args.role))


if __name__ == "__main__":
    main()
