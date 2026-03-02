"""
In-memory sliding window rate limiter.

Per-tenant request limiting based on the API key's rate_limit_rpm setting.
Suitable for single-task deployments (no shared state needed).
"""

import time
from collections import defaultdict

from fastapi import Depends, HTTPException
from starlette.responses import JSONResponse

from app.api.middleware.auth import TenantContext, get_tenant_context


class SlidingWindowRateLimiter:
    """Simple sliding-window rate limiter using an in-memory dict."""

    def __init__(self):
        # {tenant_id: [timestamp, timestamp, ...]}
        self._windows: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, tenant_id: str, max_rpm: int) -> bool:
        """Check if a request is allowed within the rate limit window."""
        now = time.monotonic()
        window_start = now - 60.0  # 1-minute sliding window

        # Prune old entries
        timestamps = self._windows[tenant_id]
        self._windows[tenant_id] = [t for t in timestamps if t > window_start]

        if len(self._windows[tenant_id]) >= max_rpm:
            return False

        self._windows[tenant_id].append(now)
        return True


# Module-level singleton (fine for single-task deployment)
_rate_limiter = SlidingWindowRateLimiter()


async def check_rate_limit(
    tenant: TenantContext = Depends(get_tenant_context),
) -> TenantContext:
    """
    FastAPI dependency that wraps get_tenant_context with rate limiting.

    Use this instead of get_tenant_context in routes that need rate limiting.
    Returns 429 with Retry-After header if limit exceeded.
    """
    tenant_key = str(tenant.tenant_id)

    if not _rate_limiter.is_allowed(tenant_key, tenant.rate_limit_rpm):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": "60"},
        )

    return tenant
