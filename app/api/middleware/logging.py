"""
Request logging middleware.

Logs request_id, tenant_id, method, path, status_code, duration_ms, client_ip.
Adds X-Request-ID and X-Response-Time-Ms response headers.
"""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("curateai.requests")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        start = time.monotonic()

        # Attach request_id to request state for downstream use
        request.state.request_id = request_id

        response: Response = await call_next(request)

        duration_ms = round((time.monotonic() - start) * 1000, 1)

        # Add response headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(duration_ms)

        # Extract tenant_id if available (set by auth middleware on request.state)
        tenant_id = getattr(request.state, "tenant_id", None)
        client_ip = request.client.host if request.client else "unknown"

        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "tenant_id": str(tenant_id) if tenant_id else None,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": client_ip,
            },
        )

        return response
