"""DentalServicesVertical — Vertical Protocol implementation.

Phase 1 wires the dental graph (currently a single placeholder node) to the
kernel. State construction is minimal; persistence is limited to whatever
the placeholder node mutates. Phase 2 will extend `finalize` to map
treatments, doctors, comparisons, and CTAs into the polymorphic ChatResponse.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.shared.response import ChatItem, ChatResponse, CtaLink
from app.agents.verticals.dental_services.graph import get_dental_graph
from app.agents.verticals.dental_services.state import DentalAgentState

if TYPE_CHECKING:
    from app.db.repositories.session import SessionRepository


class DentalServicesVertical:
    """Adapter for the dental_services vertical."""

    name = "dental_services"

    def create_state(
        self,
        *,
        session_id: uuid.UUID,
        user_message: str,
        existing_context: dict | None,
        existing_status: str,
        previous_response: str | None,
        tenant_id: uuid.UUID,
        tenant_enabled_domains: list[str],
        vertical_context_seed: dict | None = None,
    ) -> DentalAgentState:
        return DentalAgentState(
            session_id=session_id,
            user_message=user_message,
            tenant_id=tenant_id,
            tenant_enabled_domains=tenant_enabled_domains,
            status=existing_status,
            extracted_context=existing_context or {},
            previous_response=previous_response,
            vertical_context=vertical_context_seed or {},
            response=None,
            items=[],
            cta_links=[],
            suggested_replies=[],
        )

    async def run(self, state: DentalAgentState, db: AsyncSession) -> DentalAgentState:
        # db isn't used by the Phase 1 placeholder graph; Phase 2 agents
        # (doctor_search, content_qa) will read from dental repositories.
        graph = get_dental_graph()
        return await graph.run(state)

    async def finalize(
        self,
        state: DentalAgentState,
        session_repo: "SessionRepository",
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> tuple[ChatResponse, list[uuid.UUID]]:
        items_raw = state.get("items") or []
        cta_links_raw = state.get("cta_links") or []

        response = ChatResponse(
            session_id=session_id,
            response=state.get("response")
            or "Sorry, the dental consultation didn't produce a response.",
            status=state.get("status", "active"),
            items=[ChatItem(**i) for i in items_raw],
            cta_links=[CtaLink(**c) for c in cta_links_raw],
            suggested_replies=state.get("suggested_replies") or [],
            vertical_context=state.get("vertical_context") or {},
        )

        # Phase 1 has no item IDs to persist with the assistant message.
        return response, []
