"""
API Key authentication middleware.

Extracts tenant context from X-API-Key header. Falls back to the seed
tenant when no key is provided (backward compatibility for existing widget).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.repositories.tenant import TenantRepository

# Seed tenant UUID (created in migration 005)
SEED_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@dataclass
class TenantContext:
    tenant_id: uuid.UUID
    tenant_slug: str
    enabled_domains: list[str]
    allowed_origins: list[str]
    rate_limit_rpm: int
    daily_cost_cap_cents: int
    user_id: uuid.UUID | None = None


async def get_tenant_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    """
    FastAPI dependency that resolves the tenant from the request.

    Resolution order:
    1. X-API-Key header → hash → lookup → IP check → expiry check
    2. No key → fall back to seed tenant (backward compat)
    """
    tenant_repo = TenantRepository(db)
    api_key_header = request.headers.get("X-API-Key")

    if api_key_header:
        # --- Authenticate via API key ---
        result = await tenant_repo.lookup_api_key(api_key_header)
        if result is None:
            raise HTTPException(status_code=401, detail="Invalid API key")

        api_key, tenant = result

        # Check expiry
        if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="API key has expired")

        # Check IP allowlist
        if api_key.allowed_ips:
            client_ip = request.client.host if request.client else None
            if client_ip and client_ip not in api_key.allowed_ips:
                raise HTTPException(
                    status_code=403,
                    detail="Request from unauthorized IP address",
                )

        # Check Origin against tenant's allowed_origins
        origin = request.headers.get("origin")
        if tenant.allowed_origins and "*" not in tenant.allowed_origins:
            if origin and origin not in tenant.allowed_origins:
                raise HTTPException(
                    status_code=403,
                    detail="Request from unauthorized origin",
                )

        # Update last_used_at (fire-and-forget, don't block response)
        await tenant_repo.touch_api_key(api_key.id)

        # Extract user_id from custom header (set by widget/client)
        user_id_str = request.headers.get("X-User-ID")
        user_id = None
        if user_id_str:
            try:
                user_id = uuid.UUID(user_id_str)
            except ValueError:
                pass

        return TenantContext(
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            enabled_domains=list(tenant.enabled_domains),
            allowed_origins=list(tenant.allowed_origins),
            rate_limit_rpm=api_key.rate_limit_rpm,
            daily_cost_cap_cents=tenant.daily_bedrock_cost_cap_cents,
            user_id=user_id,
        )

    # --- Fallback: seed tenant (no API key provided) ---
    seed_tenant = await tenant_repo.get_by_id(SEED_TENANT_ID)
    if seed_tenant is None:
        raise HTTPException(
            status_code=500,
            detail="Default tenant not found. Run migrations first.",
        )

    return TenantContext(
        tenant_id=seed_tenant.id,
        tenant_slug=seed_tenant.slug,
        enabled_domains=list(seed_tenant.enabled_domains),
        allowed_origins=list(seed_tenant.allowed_origins),
        rate_limit_rpm=60,
        daily_cost_cap_cents=seed_tenant.daily_bedrock_cost_cap_cents,
    )
