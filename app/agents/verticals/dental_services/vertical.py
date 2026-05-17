"""DentalServicesVertical — Vertical Protocol implementation.

Hydrates multi-turn state (filled_slots, candidate_concern_id,
shown_treatments, pending_slot_*) from session.extracted_context on entry,
and writes it back on finalize so the kernel can persist it.
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


# Keys inside extracted_context that the dental vertical persists across turns
_PERSISTED_KEYS = (
    "candidate_concern_id",
    "filled_slots",
    "pending_slot_id",
    "pending_slot_question",
    "shown_treatments",
)


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
        ctx = dict(existing_context or {})

        state: DentalAgentState = DentalAgentState(
            session_id=session_id,
            user_message=user_message,
            tenant_id=tenant_id,
            tenant_enabled_domains=tenant_enabled_domains,
            status=existing_status,
            extracted_context=ctx,
            previous_response=previous_response,
            vertical_context=vertical_context_seed or {},
            response=None,
            items=[],
            cta_links=[],
            suggested_replies=[],
            # Hydrate persisted multi-turn fields from extracted_context.
            candidate_concern_id=ctx.get("candidate_concern_id"),
            filled_slots=dict(ctx.get("filled_slots") or {}),
            pending_slot_question=ctx.get("pending_slot_question"),
            missing_slots=[],
            candidate_treatments=[],
            recommended_treatment_ids=[],
            doctor_filters=None,
            matched_doctors=[],
            comparison_payload=None,
            treatment_stack=None,
            content_citations=[],
            requires_clinical_review=False,
            escalation_reason=None,
            service_context=None,
            intent_type=None,
            next_agent=None,
        )
        return state

    async def run(self, state: DentalAgentState, db: AsyncSession) -> DentalAgentState:
        graph = get_dental_graph()
        return await graph.run(state, db)

    async def finalize(
        self,
        state: DentalAgentState,
        session_repo: "SessionRepository",
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> tuple[ChatResponse, list[uuid.UUID]]:
        # Dehydrate: write multi-turn fields back into extracted_context
        # so the kernel's update_context call persists them.
        ctx = state.get("extracted_context") or {}
        ctx["candidate_concern_id"] = state.get("candidate_concern_id")
        ctx["filled_slots"] = state.get("filled_slots") or {}
        # pending_slot_id is set inside extracted_context directly by the interviewer.
        # If a recommender/safety reached completed, the interviewer cleared it already.
        if state.get("status") == "completed":
            ctx.pop("pending_slot_id", None)
            ctx.pop("pending_slot_question", None)
        state["extracted_context"] = ctx

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

        # No commerce-style suggested_product_ids on the message yet — Phase 2
        # service-detail / refinement matching uses extracted_context.shown_treatments.
        return response, []
