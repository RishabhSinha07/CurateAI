"""
Admin authentication middleware.

Issues and verifies self-signed JWTs for admin dashboard access.
Maps authenticated admins to their tenant via the admin_users table.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.db.models import AdminUser

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(admin_id: uuid.UUID, email: str) -> str:
    """Create a signed JWT for an authenticated admin."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(admin_id),
        "email": email,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expiry_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT. Raises jwt.PyJWTError on failure."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])


@dataclass
class AdminContext:
    admin_id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    role: str


async def get_admin_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AdminContext:
    """
    FastAPI dependency that authenticates an admin via self-signed JWT
    and resolves their tenant.

    1. Extract Bearer token from Authorization header
    2. Decode & verify JWT
    3. Look up admin_users by id (from sub claim)
    4. Return AdminContext with tenant_id
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authorization header with Bearer token required",
        )

    token = auth_header[7:]  # Strip "Bearer "

    try:
        claims = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.PyJWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

    admin_id_str = claims.get("sub")
    if not admin_id_str:
        raise HTTPException(status_code=401, detail="Token missing sub claim")

    try:
        admin_id = uuid.UUID(admin_id_str)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid admin ID in token")

    # Look up admin user
    result = await db.execute(
        select(AdminUser).where(
            AdminUser.id == admin_id,
            AdminUser.is_active == True,
        )
    )
    admin_user = result.scalar_one_or_none()

    if admin_user is None:
        raise HTTPException(
            status_code=403,
            detail="Admin account not found or deactivated.",
        )

    return AdminContext(
        admin_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        email=admin_user.email,
        role=admin_user.role,
    )
