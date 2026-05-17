"""Comparison node — side-by-side comparison of two or more treatments.
Stub in slice A; real implementation in slice E.
"""

from __future__ import annotations

from app.agents.verticals.dental_services.state import DentalAgentState


async def comparison_agent(state: DentalAgentState) -> DentalAgentState:
    state["response"] = (
        "I can put together a side-by-side comparison weighted by your priorities "
        "(timeline, cost, visibility, durability). That comparator lands next."
    )
    state.setdefault("comparison_payload", None)
    state.setdefault("items", [])
    state.setdefault("cta_links", [])
    return state
