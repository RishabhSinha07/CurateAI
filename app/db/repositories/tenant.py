import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey, Tenant


class TenantRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, tenant_id: uuid.UUID) -> Tenant | None:
        return await self.session.get(Tenant, tenant_id)

    async def get_by_slug(self, slug: str) -> Tenant | None:
        result = await self.session.execute(
            select(Tenant).where(Tenant.slug == slug, Tenant.is_active == True)
        )
        return result.scalar_one_or_none()

    async def lookup_api_key(self, raw_key: str) -> tuple[ApiKey, Tenant] | None:
        """Hash the raw API key and look up the corresponding ApiKey + Tenant."""
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        result = await self.session.execute(
            select(ApiKey, Tenant)
            .join(Tenant, ApiKey.tenant_id == Tenant.id)
            .where(
                ApiKey.key_hash == key_hash,
                ApiKey.is_active == True,
                Tenant.is_active == True,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        return row[0], row[1]

    async def touch_api_key(self, api_key_id: uuid.UUID) -> None:
        """Update last_used_at timestamp."""
        await self.session.execute(
            update(ApiKey)
            .where(ApiKey.id == api_key_id)
            .values(last_used_at=datetime.now(timezone.utc))
        )

    async def create_api_key(
        self,
        tenant_id: uuid.UUID,
        label: str | None = None,
        allowed_ips: list[str] | None = None,
        rate_limit_rpm: int = 60,
    ) -> tuple[ApiKey, str]:
        """
        Create a new API key for a tenant.

        Returns (ApiKey model, raw_key). The raw key is only available at creation.
        """
        raw_key = f"cai_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:8]

        api_key = ApiKey(
            tenant_id=tenant_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            label=label,
            allowed_ips=allowed_ips,
            rate_limit_rpm=rate_limit_rpm,
        )
        self.session.add(api_key)
        await self.session.flush()
        return api_key, raw_key

    async def deactivate_api_key(self, api_key_id: uuid.UUID) -> None:
        await self.session.execute(
            update(ApiKey)
            .where(ApiKey.id == api_key_id)
            .values(is_active=False)
        )
