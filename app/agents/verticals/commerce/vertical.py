"""Commerce vertical implementation.

Adapts the existing ConsultationGraph to the Vertical protocol. The agent
internals (router, interviewer, etc.) are unchanged from before Phase 0;
this module is responsible for the kernel-facing seams: state construction,
session-side persistence, and translation of the commerce-shaped agent
state into the polymorphic wire response.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.shared.response import ChatItem, ChatResponse
from app.agents.verticals.commerce.graph import create_initial_state, get_consultation_graph
from app.agents.verticals.commerce.state import AgentState

if TYPE_CHECKING:
    from app.db.repositories.session import SessionRepository


class CommerceVertical:
    """Vertical adapter for product-recommendation tenants."""

    name = "commerce"

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
    ) -> AgentState:
        seed = vertical_context_seed or {}
        return create_initial_state(
            session_id=session_id,
            user_message=user_message,
            existing_context=existing_context,
            existing_status=existing_status,
            domain_slug=seed.get("domain_slug"),
            previous_response=previous_response,
            tenant_id=tenant_id,
            tenant_enabled_domains=tenant_enabled_domains,
        )

    async def run(self, state: AgentState, db: AsyncSession) -> AgentState:
        graph = get_consultation_graph()
        return await graph.run(state, db)

    async def finalize(
        self,
        state: AgentState,
        session_repo: "SessionRepository",
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> tuple[ChatResponse, list[uuid.UUID]]:
        # Use final (personalised) products when available, else fall back
        # to the initial domain products shown during the first interview pass.
        final_products = state.get("final_products") or []
        display_products = final_products or state.get("initial_products", []) or []

        # Persist shown products so subsequent turns can reference them
        # (router PDA matching, refinement filtering, etc.).
        if display_products:
            ctx = state.get("extracted_context") or {}
            ctx["shown_products"] = [
                {
                    k: p.get(k)
                    for k in (
                        "id",
                        "name",
                        "brand",
                        "description",
                        "price",
                        "currency",
                        "product_url",
                        "image_url",
                        "attributes",
                        "match_reasons",
                    )
                }
                for p in display_products[:8]
            ]
            state["extracted_context"] = ctx
            await session_repo.update_context(session_id, ctx)

        # Persist the current domain on the session row.
        new_domain = state.get("domain_slug")
        if new_domain and new_domain != state.get("previous_domain_slug"):
            await session_repo.set_domain(session_id, new_domain)

        # Map state → polymorphic items.
        items: list[ChatItem] = [_product_to_item(p) for p in display_products]

        # Product Detail Agent response: surface the deep-dive product too.
        if state.get("product_context"):
            items.insert(0, _product_to_item(state["product_context"], detail=True))

        response_text = (
            state.get("response")
            or "I'm sorry, I couldn't process your request. Please try again."
        )

        chat_response = ChatResponse(
            session_id=session_id,
            response=response_text,
            status=state.get("status", "active"),
            items=items,
            cta_links=[],  # commerce has no explicit CTAs today
            suggested_replies=state.get("suggested_replies") or [],
            vertical_context={
                "domain_slug": state.get("domain_slug"),
                "intent_type": state.get("intent_type"),
                "journey_info": state.get("journey_bundle"),
            },
        )

        item_ids: list[uuid.UUID] = []
        for p in display_products:
            try:
                item_ids.append(uuid.UUID(p["id"]))
            except (KeyError, ValueError, TypeError):
                continue

        return chat_response, item_ids


def _product_to_item(p: dict[str, Any], *, detail: bool = False) -> ChatItem:
    """Map a commerce product dict to the polymorphic ChatItem shape."""
    attributes: dict[str, Any] = dict(p.get("attributes") or {})
    if detail:
        attributes["detail"] = True
    return ChatItem(
        type="product",
        id=str(p.get("id", "")),
        title=p.get("name") or "",
        subtitle=p.get("brand"),
        price=p.get("price"),
        currency=p.get("currency", "USD"),
        image_url=p.get("image_url"),
        url=p.get("product_url"),
        description=p.get("description"),
        badges=list(p.get("match_reasons") or []),
        attributes=attributes,
    )
