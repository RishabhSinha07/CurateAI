"""
Admin endpoints for product upload and API key management.

Protected by Cognito JWT (require_admin dependency).
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import Product
from app.db.repositories.tenant import TenantRepository
from app.api.middleware.auth import TenantContext, get_tenant_context
from app.api.middleware.admin import require_admin
from app.services.embeddings import generate_embedding_async

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ============================================
# Product Upload
# ============================================


class ProductCreateRequest(BaseModel):
    domain_slugs: list[str] = Field(..., min_length=1)
    sku: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    brand: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    currency: str = "USD"
    product_url: Optional[str] = None
    image_url: Optional[str] = None
    attributes: dict = Field(default_factory=dict)


class ProductCreateResponse(BaseModel):
    id: uuid.UUID
    name: str
    embedding_generated: bool


@router.post("/products", response_model=ProductCreateResponse)
async def create_product(
    request: ProductCreateRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ProductCreateResponse:
    """
    Create a product with auto-generated embedding.

    Validates domain_slugs against tenant's enabled_domains.
    """
    # Validate domains against tenant's enabled list
    if "*" not in tenant.enabled_domains:
        invalid = set(request.domain_slugs) - set(tenant.enabled_domains)
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Domain(s) not enabled for this tenant: {', '.join(invalid)}",
            )

    # Create product
    product = Product(
        tenant_id=tenant.tenant_id,
        domain_slugs=request.domain_slugs,
        sku=request.sku,
        name=request.name,
        brand=request.brand,
        description=request.description,
        price=request.price,
        currency=request.currency,
        product_url=request.product_url,
        image_url=request.image_url,
        attributes=request.attributes,
    )
    db.add(product)
    await db.flush()

    # Generate embedding
    embedding_generated = False
    if request.description:
        try:
            embedding = await generate_embedding_async(request.description)
            product.description_embedding = embedding
            embedding_generated = True
        except Exception:
            pass  # Product created without embedding; can be generated later

    return ProductCreateResponse(
        id=product.id,
        name=product.name,
        embedding_generated=embedding_generated,
    )


# ============================================
# API Key Rotation
# ============================================


class KeyRotateRequest(BaseModel):
    old_key: str = Field(..., description="Current API key to rotate")


class KeyRotateResponse(BaseModel):
    new_key: str
    key_prefix: str
    old_key_deactivated: bool


@router.post("/api-keys/rotate", response_model=KeyRotateResponse)
async def rotate_api_key(
    request: KeyRotateRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> KeyRotateResponse:
    """
    Rotate an API key: create new key with same settings, deactivate old.

    The old key must belong to the requesting tenant.
    """
    tenant_repo = TenantRepository(db)

    # Verify old key
    result = await tenant_repo.lookup_api_key(request.old_key)
    if result is None:
        raise HTTPException(status_code=400, detail="Old API key not found or inactive")

    old_api_key, key_tenant = result
    if key_tenant.id != tenant.tenant_id:
        raise HTTPException(status_code=403, detail="API key does not belong to this tenant")

    # Create new key with same settings
    new_api_key, raw_key = await tenant_repo.create_api_key(
        tenant_id=tenant.tenant_id,
        label=f"Rotated from {old_api_key.key_prefix}...",
        allowed_ips=old_api_key.allowed_ips,
        rate_limit_rpm=old_api_key.rate_limit_rpm,
    )

    # Deactivate old key
    await tenant_repo.deactivate_api_key(old_api_key.id)

    return KeyRotateResponse(
        new_key=raw_key,
        key_prefix=new_api_key.key_prefix,
        old_key_deactivated=True,
    )
