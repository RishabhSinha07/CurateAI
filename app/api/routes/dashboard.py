"""
Dashboard analytics endpoints + admin login.

All dashboard endpoints are scoped to the authenticated admin's tenant
via self-signed JWT auth.
"""

import logging
import uuid
from datetime import date
from decimal import Decimal
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import AdminUser
from app.db.repositories.dashboard import DashboardRepository
from app.api.middleware.cognito import (
    AdminContext,
    create_access_token,
    get_admin_context,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/dashboard", tags=["dashboard"])


# ============================================
# Enums
# ============================================


class Granularity(str, Enum):
    day = "day"
    week = "week"
    month = "month"


class ProductSortBy(str, Enum):
    recommended = "recommended"
    clicked = "clicked"
    conversion = "conversion"


# ============================================
# Response Models — Overview
# ============================================


class OverviewResponse(BaseModel):
    total_sessions: int
    unique_users: int
    total_messages: int
    avg_messages_per_session: float
    avg_session_duration_seconds: float | None
    completion_rate_pct: float
    drop_off_rate_pct: float
    status_breakdown: dict[str, int]
    domain_breakdown: dict[str, int]


# ============================================
# Response Models — Traffic
# ============================================


class TrafficPeriod(BaseModel):
    period: date
    sessions: int


class PeakHour(BaseModel):
    day_of_week: int
    hour: int
    sessions: int


class TrafficResponse(BaseModel):
    daily_sessions: list[TrafficPeriod]
    peak_hours: list[PeakHour]


# ============================================
# Response Models — Funnel
# ============================================


class FunnelStage(BaseModel):
    total: int
    unique_sessions: int


class FunnelData(BaseModel):
    total_sessions: int
    sessions_with_recommendations: int
    unique_products_recommended: int
    clicks: FunnelStage
    add_to_cart: FunnelStage
    purchases: FunnelStage


class DailyEvent(BaseModel):
    day: date
    click: int
    add_to_cart: int
    purchase: int


class FunnelResponse(BaseModel):
    funnel: FunnelData
    daily_events: list[DailyEvent]


# ============================================
# Response Models — Products
# ============================================


class ProductMetric(BaseModel):
    id: uuid.UUID
    name: str
    brand: str | None
    price: Decimal | None
    times_recommended: int
    clicks: int
    add_to_cart: int
    purchases: int
    conversion_pct: float


class ProductsResponse(BaseModel):
    products: list[ProductMetric]
    never_recommended_count: int


# ============================================
# Response Models — Product Detail
# ============================================


class ProductInfo(BaseModel):
    id: uuid.UUID
    name: str
    brand: str | None
    price: Decimal | None


class EventCounts(BaseModel):
    click: int
    add_to_cart: int
    purchase: int


class ProductDetailResponse(BaseModel):
    product: ProductInfo
    times_recommended: int
    events: EventCounts
    daily_events: list[DailyEvent]


# ============================================
# Login
# ============================================


class LoginRequest(BaseModel):
    email: str = Field(..., description="Admin email address")
    password: str = Field(..., min_length=1, description="Admin password")


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin_id: uuid.UUID
    email: str
    role: str
    tenant_id: uuid.UUID


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Authenticate an admin and return a JWT access token."""
    result = await db.execute(
        select(AdminUser).where(
            AdminUser.email == request.email,
            AdminUser.is_active == True,
        )
    )
    admin_user = result.scalar_one_or_none()

    if admin_user is None or not verify_password(request.password, admin_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(admin_user.id, admin_user.email)

    return LoginResponse(
        access_token=token,
        admin_id=admin_user.id,
        email=admin_user.email,
        role=admin_user.role,
        tenant_id=admin_user.tenant_id,
    )


# ============================================
# Dashboard Endpoints
# ============================================


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    start_date: date = Query(..., description="Start date (inclusive)"),
    end_date: date = Query(..., description="End date (inclusive)"),
    admin: AdminContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
) -> OverviewResponse:
    """Get overview KPI metrics for the tenant."""
    repo = DashboardRepository(db)
    data = await repo.get_overview(admin.tenant_id, start_date, end_date)
    return OverviewResponse(**data)


@router.get("/traffic", response_model=TrafficResponse)
async def get_traffic(
    start_date: date = Query(..., description="Start date (inclusive)"),
    end_date: date = Query(..., description="End date (inclusive)"),
    granularity: Granularity = Query(Granularity.day, description="Time bucket granularity"),
    admin: AdminContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
) -> TrafficResponse:
    """Get session traffic trends and peak hours."""
    repo = DashboardRepository(db)
    data = await repo.get_traffic(admin.tenant_id, start_date, end_date, granularity.value)
    return TrafficResponse(**data)


@router.get("/funnel", response_model=FunnelResponse)
async def get_funnel(
    start_date: date = Query(..., description="Start date (inclusive)"),
    end_date: date = Query(..., description="End date (inclusive)"),
    admin: AdminContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
) -> FunnelResponse:
    """Get conversion funnel: sessions -> recommendations -> clicks -> cart -> purchases."""
    repo = DashboardRepository(db)
    data = await repo.get_funnel(admin.tenant_id, start_date, end_date)
    return FunnelResponse(**data)


@router.get("/products", response_model=ProductsResponse)
async def get_products(
    start_date: date = Query(..., description="Start date (inclusive)"),
    end_date: date = Query(..., description="End date (inclusive)"),
    sort_by: ProductSortBy = Query(ProductSortBy.recommended, description="Sort products by"),
    limit: int = Query(10, ge=1, le=100, description="Max products to return"),
    admin: AdminContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
) -> ProductsResponse:
    """Get top products with recommendation, click, and conversion metrics."""
    repo = DashboardRepository(db)
    data = await repo.get_top_products(
        admin.tenant_id, start_date, end_date, sort_by.value, limit
    )
    return ProductsResponse(**data)


@router.get("/products/{product_id}", response_model=ProductDetailResponse)
async def get_product_detail(
    product_id: uuid.UUID,
    start_date: date = Query(..., description="Start date (inclusive)"),
    end_date: date = Query(..., description="End date (inclusive)"),
    admin: AdminContext = Depends(get_admin_context),
    db: AsyncSession = Depends(get_db),
) -> ProductDetailResponse:
    """Get detailed metrics for a single product."""
    repo = DashboardRepository(db)
    try:
        data = await repo.get_product_detail(admin.tenant_id, product_id, start_date, end_date)
    except Exception as e:
        # Surface the underlying exception both to logs (CloudWatch) and to
        # the response so we can diagnose without server access.
        logger.exception("get_product_detail failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
    if data is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductDetailResponse(**data)
