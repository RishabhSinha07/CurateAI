"""Service detail — deep Q&A on a previously shown service (analog of product_detail).
Stub in slice A; real implementation in slice G.
"""

from __future__ import annotations

from app.agents.verticals.dental_services.state import DentalAgentState


async def service_detail_agent(state: DentalAgentState) -> DentalAgentState:
    state["response"] = (
        "I can answer detailed questions about a specific Dezy treatment — pain, "
        "duration, recovery, sittings. Service-detail Q&A is coming online."
    )
    state.setdefault("items", [])
    state.setdefault("cta_links", [])
    return state
