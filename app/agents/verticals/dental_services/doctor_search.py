"""Doctor search — multi-attribute filter over the doctors table.
Stub in slice A; real implementation in slice D.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.verticals.dental_services.state import DentalAgentState


async def doctor_search_agent(state: DentalAgentState, db: AsyncSession) -> DentalAgentState:
    filters = state.get("doctor_filters") or {}
    parts = ", ".join(f"{k}={v}" for k, v in filters.items()) or "no filters parsed"
    state["response"] = (
        f"Doctor search is being wired up ({parts}). When live, this returns "
        "matching Dezy clinicians with bios and a book-with-doctor link."
    )
    state.setdefault("matched_doctors", [])
    state.setdefault("items", [])
    state.setdefault("cta_links", [])
    return state
