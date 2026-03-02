"""
Admin guard dependency.

Requires a Cognito JWT via Authorization: Bearer header.
API-key-only requests are rejected on admin routes.
"""

from fastapi import Depends, HTTPException, Request


async def require_admin(request: Request) -> None:
    """
    FastAPI dependency that ensures the request has a Bearer token.

    The JWT is already validated by the API Gateway Cognito authorizer.
    This guard simply ensures the request came through the authenticated
    API Gateway path (has Authorization header) rather than via API key only.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Admin endpoints require Cognito authentication (Bearer token)",
        )
