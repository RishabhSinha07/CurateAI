"""
Dashboard analytics repository.

Read-only queries for tenant dashboard metrics. All methods filter
by tenant_id and a [start, end) date range.
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import Select, and_, any_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage, ChatSession, Product, ProductEvent


class DashboardRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _date_range(start: date, end: date) -> tuple[datetime, datetime]:
        """Convert date params to UTC-aware half-open interval [start, end+1day)."""
        start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
        return start_dt, end_dt

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------

    async def get_overview(
        self, tenant_id: uuid.UUID, start: date, end: date
    ) -> dict:
        start_dt, end_dt = self._date_range(start, end)
        session_filters = [
            ChatSession.tenant_id == tenant_id,
            ChatSession.created_at >= start_dt,
            ChatSession.created_at < end_dt,
        ]

        # Query A: session-level aggregates
        result = await self.session.execute(
            select(
                func.count(ChatSession.id).label("total_sessions"),
                func.count(func.distinct(ChatSession.user_id)).label("unique_users"),
                func.avg(
                    func.extract("epoch", ChatSession.updated_at - ChatSession.created_at)
                ).filter(ChatSession.status == "completed").label("avg_duration"),
                func.count(ChatSession.id).filter(
                    ChatSession.status == "completed"
                ).label("completed"),
                func.count(ChatSession.id).filter(
                    ChatSession.status == "awaiting_slot"
                ).label("awaiting_slot"),
            ).where(and_(*session_filters))
        )
        row = result.one()
        total = row.total_sessions or 0
        completed = row.completed or 0
        awaiting_slot = row.awaiting_slot or 0

        # Query B: status breakdown
        result = await self.session.execute(
            select(ChatSession.status, func.count())
            .where(and_(*session_filters))
            .group_by(ChatSession.status)
        )
        status_breakdown = {status: count for status, count in result.all()}

        # Query C: domain breakdown
        result = await self.session.execute(
            select(
                func.coalesce(ChatSession.current_domain_slug, "unassigned").label("domain"),
                func.count(),
            )
            .where(and_(*session_filters))
            .group_by("domain")
        )
        domain_breakdown = {domain: count for domain, count in result.all()}

        # Query D: message count
        msg_filters = [
            ChatMessage.tenant_id == tenant_id,
            ChatMessage.created_at >= start_dt,
            ChatMessage.created_at < end_dt,
        ]
        result = await self.session.execute(
            select(func.count(ChatMessage.id)).where(and_(*msg_filters))
        )
        total_messages = result.scalar_one() or 0

        avg_messages = round(total_messages / total, 1) if total > 0 else 0.0
        completion_pct = round(completed / total * 100, 1) if total > 0 else 0.0
        drop_off_pct = round(awaiting_slot / total * 100, 1) if total > 0 else 0.0
        avg_duration = round(float(row.avg_duration), 0) if row.avg_duration else None

        return {
            "total_sessions": total,
            "unique_users": row.unique_users or 0,
            "total_messages": total_messages,
            "avg_messages_per_session": avg_messages,
            "avg_session_duration_seconds": avg_duration,
            "completion_rate_pct": completion_pct,
            "drop_off_rate_pct": drop_off_pct,
            "status_breakdown": status_breakdown,
            "domain_breakdown": domain_breakdown,
        }

    # ------------------------------------------------------------------
    # Traffic
    # ------------------------------------------------------------------

    async def get_traffic(
        self, tenant_id: uuid.UUID, start: date, end: date, granularity: str = "day"
    ) -> dict:
        start_dt, end_dt = self._date_range(start, end)
        filters = [
            ChatSession.tenant_id == tenant_id,
            ChatSession.created_at >= start_dt,
            ChatSession.created_at < end_dt,
        ]

        # Query A: sessions by period
        period_col = func.date_trunc(granularity, ChatSession.created_at).label("period")
        result = await self.session.execute(
            select(period_col, func.count().label("sessions"))
            .where(and_(*filters))
            .group_by(period_col)
            .order_by(period_col)
        )
        daily_sessions = [
            {"period": row.period.date(), "sessions": row.sessions}
            for row in result.all()
        ]

        # Query B: peak hours heatmap
        dow_col = func.extract("isodow", ChatSession.created_at).label("day_of_week")
        hour_col = func.extract("hour", ChatSession.created_at).label("hour")
        result = await self.session.execute(
            select(dow_col, hour_col, func.count().label("sessions"))
            .where(and_(*filters))
            .group_by(dow_col, hour_col)
            .order_by(func.count().desc())
        )
        peak_hours = [
            {
                "day_of_week": int(row.day_of_week),
                "hour": int(row.hour),
                "sessions": row.sessions,
            }
            for row in result.all()
        ]

        return {
            "daily_sessions": daily_sessions,
            "peak_hours": peak_hours,
        }

    # ------------------------------------------------------------------
    # Funnel
    # ------------------------------------------------------------------

    async def get_funnel(
        self, tenant_id: uuid.UUID, start: date, end: date
    ) -> dict:
        start_dt, end_dt = self._date_range(start, end)

        # Query A: total sessions
        result = await self.session.execute(
            select(func.count(ChatSession.id)).where(and_(
                ChatSession.tenant_id == tenant_id,
                ChatSession.created_at >= start_dt,
                ChatSession.created_at < end_dt,
            ))
        )
        total_sessions = result.scalar_one() or 0

        # Query B: recommendation metrics
        msg_filters = [
            ChatMessage.tenant_id == tenant_id,
            ChatMessage.suggested_product_ids.is_not(None),
            ChatMessage.created_at >= start_dt,
            ChatMessage.created_at < end_dt,
        ]
        result = await self.session.execute(
            select(func.count(func.distinct(ChatMessage.session_id))).where(and_(*msg_filters))
        )
        sessions_with_recs = result.scalar_one() or 0

        # Unique products recommended via unnest subquery
        unnested = (
            select(func.unnest(ChatMessage.suggested_product_ids).label("product_id"))
            .where(and_(*msg_filters))
            .subquery()
        )
        result = await self.session.execute(
            select(func.count(func.distinct(unnested.c.product_id)))
        )
        unique_products_recommended = result.scalar_one() or 0

        # Query C: event counts (single query with conditional aggregation)
        evt_filters = [
            ProductEvent.tenant_id == tenant_id,
            ProductEvent.created_at >= start_dt,
            ProductEvent.created_at < end_dt,
        ]
        result = await self.session.execute(
            select(
                func.count(case(
                    (ProductEvent.event_type == "click", ProductEvent.id),
                )).label("click_total"),
                func.count(func.distinct(case(
                    (ProductEvent.event_type == "click", ProductEvent.session_id),
                ))).label("click_sessions"),
                func.count(case(
                    (ProductEvent.event_type == "add_to_cart", ProductEvent.id),
                )).label("atc_total"),
                func.count(func.distinct(case(
                    (ProductEvent.event_type == "add_to_cart", ProductEvent.session_id),
                ))).label("atc_sessions"),
                func.count(case(
                    (ProductEvent.event_type == "purchase", ProductEvent.id),
                )).label("purchase_total"),
                func.count(func.distinct(case(
                    (ProductEvent.event_type == "purchase", ProductEvent.session_id),
                ))).label("purchase_sessions"),
            ).where(and_(*evt_filters))
        )
        evt = result.one()

        # Query D: daily event breakdown
        daily_events = await self._daily_events(tenant_id, start_dt, end_dt)

        return {
            "funnel": {
                "total_sessions": total_sessions,
                "sessions_with_recommendations": sessions_with_recs,
                "unique_products_recommended": unique_products_recommended,
                "clicks": {"total": evt.click_total, "unique_sessions": evt.click_sessions},
                "add_to_cart": {"total": evt.atc_total, "unique_sessions": evt.atc_sessions},
                "purchases": {
                    "total": evt.purchase_total,
                    "unique_sessions": evt.purchase_sessions,
                },
            },
            "daily_events": daily_events,
        }

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------

    async def get_top_products(
        self,
        tenant_id: uuid.UUID,
        start: date,
        end: date,
        sort_by: str = "recommended",
        limit: int = 10,
    ) -> dict:
        start_dt, end_dt = self._date_range(start, end)

        # Subquery A: recommendation counts per product
        rec_sub = (
            select(
                func.unnest(ChatMessage.suggested_product_ids).label("product_id"),
            )
            .where(and_(
                ChatMessage.tenant_id == tenant_id,
                ChatMessage.suggested_product_ids.is_not(None),
                ChatMessage.created_at >= start_dt,
                ChatMessage.created_at < end_dt,
            ))
            .subquery()
        )
        rec_counts = (
            select(
                rec_sub.c.product_id,
                func.count().label("times_recommended"),
            )
            .group_by(rec_sub.c.product_id)
            .subquery()
        )

        # Subquery B: event counts per product
        evt_counts = (
            select(
                ProductEvent.product_id,
                func.count(case(
                    (ProductEvent.event_type == "click", ProductEvent.id),
                )).label("clicks"),
                func.count(case(
                    (ProductEvent.event_type == "add_to_cart", ProductEvent.id),
                )).label("add_to_cart"),
                func.count(case(
                    (ProductEvent.event_type == "purchase", ProductEvent.id),
                )).label("purchases"),
            )
            .where(and_(
                ProductEvent.tenant_id == tenant_id,
                ProductEvent.created_at >= start_dt,
                ProductEvent.created_at < end_dt,
            ))
            .group_by(ProductEvent.product_id)
            .subquery()
        )

        # Main query: join product with both subqueries
        recs_col = func.coalesce(rec_counts.c.times_recommended, 0).label("times_recommended")
        clicks_col = func.coalesce(evt_counts.c.clicks, 0).label("clicks")
        atc_col = func.coalesce(evt_counts.c.add_to_cart, 0).label("add_to_cart")
        purchases_col = func.coalesce(evt_counts.c.purchases, 0).label("purchases")

        query: Select = (
            select(
                Product.id,
                Product.name,
                Product.brand,
                Product.price,
                recs_col,
                clicks_col,
                atc_col,
                purchases_col,
            )
            .outerjoin(rec_counts, Product.id == rec_counts.c.product_id)
            .outerjoin(evt_counts, Product.id == evt_counts.c.product_id)
            .where(and_(Product.tenant_id == tenant_id, Product.is_active == True))
        )

        # Sort
        sort_map = {
            "recommended": recs_col.desc(),
            "clicked": clicks_col.desc(),
            "conversion": (
                case(
                    (recs_col > 0, purchases_col * 1.0 / recs_col),
                    else_=0,
                ).desc()
            ),
        }
        query = query.order_by(sort_map.get(sort_by, recs_col.desc()))

        # Only include products that have at least one recommendation or event
        query = query.where(
            (rec_counts.c.times_recommended.is_not(None))
            | (evt_counts.c.clicks.is_not(None))
        )

        query = query.limit(limit)

        result = await self.session.execute(query)
        rows = result.all()

        products = []
        for row in rows:
            recs = row.times_recommended
            purch = row.purchases
            conversion = round(purch / recs * 100, 1) if recs > 0 else 0.0
            products.append({
                "id": row.id,
                "name": row.name,
                "brand": row.brand,
                "price": row.price,
                "times_recommended": recs,
                "clicks": row.clicks,
                "add_to_cart": row.add_to_cart,
                "purchases": purch,
                "conversion_pct": conversion,
            })

        # Never-recommended count
        recommended_ids = (
            select(func.unnest(ChatMessage.suggested_product_ids).label("pid"))
            .where(and_(
                ChatMessage.tenant_id == tenant_id,
                ChatMessage.suggested_product_ids.is_not(None),
                ChatMessage.created_at >= start_dt,
                ChatMessage.created_at < end_dt,
            ))
            .distinct()
            .subquery()
        )
        result = await self.session.execute(
            select(func.count()).select_from(Product).where(and_(
                Product.tenant_id == tenant_id,
                Product.is_active == True,
                ~Product.id.in_(select(recommended_ids.c.pid)),
            ))
        )
        never_recommended_count = result.scalar_one() or 0

        return {
            "products": products,
            "never_recommended_count": never_recommended_count,
        }

    # ------------------------------------------------------------------
    # Product Detail
    # ------------------------------------------------------------------

    async def get_product_detail(
        self,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
        start: date,
        end: date,
    ) -> dict | None:
        start_dt, end_dt = self._date_range(start, end)

        # Query A: product info
        result = await self.session.execute(
            select(Product).where(and_(
                Product.id == product_id,
                Product.tenant_id == tenant_id,
            ))
        )
        product = result.scalar_one_or_none()
        if product is None:
            return None

        # Query B: recommendation count.
        # Use `product_id = ANY(suggested_product_ids)` — `.contains()` is
        # not implemented on the abstract sqlalchemy.ARRAY type used by
        # the model, only on the postgres-dialect ARRAY.
        msg_filters = [
            ChatMessage.tenant_id == tenant_id,
            ChatMessage.suggested_product_ids.is_not(None),
            product_id == any_(ChatMessage.suggested_product_ids),
            ChatMessage.created_at >= start_dt,
            ChatMessage.created_at < end_dt,
        ]
        result = await self.session.execute(
            select(func.count(ChatMessage.id)).where(and_(*msg_filters))
        )
        times_recommended = result.scalar_one() or 0

        # Query C: event totals
        evt_filters = [
            ProductEvent.tenant_id == tenant_id,
            ProductEvent.product_id == product_id,
            ProductEvent.created_at >= start_dt,
            ProductEvent.created_at < end_dt,
        ]
        result = await self.session.execute(
            select(ProductEvent.event_type, func.count())
            .where(and_(*evt_filters))
            .group_by(ProductEvent.event_type)
        )
        events_map = {etype: count for etype, count in result.all()}

        # Query D: daily events for this product
        daily_events = await self._daily_events(
            tenant_id, start_dt, end_dt, product_id=product_id
        )

        return {
            "product": {
                "id": product.id,
                "name": product.name,
                "brand": product.brand,
                "price": product.price,
            },
            "times_recommended": times_recommended,
            "events": {
                "click": events_map.get("click", 0),
                "add_to_cart": events_map.get("add_to_cart", 0),
                "purchase": events_map.get("purchase", 0),
            },
            "daily_events": daily_events,
        }

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _daily_events(
        self,
        tenant_id: uuid.UUID,
        start_dt: datetime,
        end_dt: datetime,
        product_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """Fetch daily event breakdown, optionally filtered to a single product."""
        filters = [
            ProductEvent.tenant_id == tenant_id,
            ProductEvent.created_at >= start_dt,
            ProductEvent.created_at < end_dt,
        ]
        if product_id is not None:
            filters.append(ProductEvent.product_id == product_id)

        day_col = func.date_trunc("day", ProductEvent.created_at).label("day")
        result = await self.session.execute(
            select(day_col, ProductEvent.event_type, func.count().label("cnt"))
            .where(and_(*filters))
            .group_by(day_col, ProductEvent.event_type)
            .order_by(day_col)
        )

        # Pivot rows into {day, click, add_to_cart, purchase}
        pivot: dict[date, dict] = {}
        for row in result.all():
            d = row.day.date()
            if d not in pivot:
                pivot[d] = {"day": d, "click": 0, "add_to_cart": 0, "purchase": 0}
            pivot[d][row.event_type] = row.cnt

        return sorted(pivot.values(), key=lambda x: x["day"])
