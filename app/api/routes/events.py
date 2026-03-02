"""
Product event tracking endpoint.

Records click, add_to_cart, and purchase events for analytics.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import ProductEvent
from app.api.middleware.auth import TenantContext, get_tenant_context

router = APIRouter(prefix="/events", tags=["events"])


class EventRequest(BaseModel):
    session_id: Optional[uuid.UUID] = None
    product_id: Optional[uuid.UUID] = None
    event_type: str = Field(..., pattern="^(click|add_to_cart|purchase)$")
    metadata: Optional[dict] = None


class EventResponse(BaseModel):
    id: uuid.UUID
    status: str = "recorded"


@router.post("", response_model=EventResponse)
async def record_event(
    request: EventRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> EventResponse:
    """Record a product interaction event."""
    event = ProductEvent(
        tenant_id=tenant.tenant_id,
        session_id=request.session_id,
        product_id=request.product_id,
        event_type=request.event_type,
        metadata_=request.metadata,
    )
    db.add(event)
    await db.flush()

    return EventResponse(id=event.id)
