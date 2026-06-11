"""Repository for widget_users — anonymous-or-registered visitors.

Encapsulates the lead-capture gate: each call to `register_message` returns
the post-increment state so the /chat handler can decide whether to short-
circuit with `status="auth_required"`.
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WidgetUser


class WidgetUserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(
        self, tenant_id: uuid.UUID, anonymous_id: str
    ) -> WidgetUser | None:
        result = await self.session.execute(
            select(WidgetUser).where(
                WidgetUser.tenant_id == tenant_id,
                WidgetUser.anonymous_id == anonymous_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self, tenant_id: uuid.UUID, anonymous_id: str
    ) -> WidgetUser:
        """Idempotent insert. Concurrent first-message races resolve cleanly via
        the (tenant_id, anonymous_id) unique constraint."""
        existing = await self.get(tenant_id, anonymous_id)
        if existing is not None:
            return existing

        stmt = (
            pg_insert(WidgetUser)
            .values(tenant_id=tenant_id, anonymous_id=anonymous_id)
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "anonymous_id"]
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

        # Re-read; on_conflict_do_nothing returns no row when conflict fires.
        widget_user = await self.get(tenant_id, anonymous_id)
        assert widget_user is not None
        return widget_user

    async def increment_message_count(self, widget_user_id: uuid.UUID) -> int:
        """Bump message_count by 1 atomically and return the new value."""
        result = await self.session.execute(
            update(WidgetUser)
            .where(WidgetUser.id == widget_user_id)
            .values(message_count=WidgetUser.message_count + 1)
            .returning(WidgetUser.message_count)
        )
        new_count = result.scalar_one()
        return int(new_count)

    async def mark_registered(
        self,
        tenant_id: uuid.UUID,
        anonymous_id: str,
        name: str,
        email: str,
        phone: str,
    ) -> WidgetUser:
        """Flip is_registered and store the captured fields. Creates the row
        if a register call arrives before any /chat call did."""
        widget_user = await self.get_or_create(tenant_id, anonymous_id)
        await self.session.execute(
            update(WidgetUser)
            .where(WidgetUser.id == widget_user.id)
            .values(
                name=name,
                email=email,
                phone=phone,
                is_registered=True,
            )
        )
        await self.session.flush()
        refreshed = await self.get(tenant_id, anonymous_id)
        assert refreshed is not None
        return refreshed
