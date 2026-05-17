"""Treatment planner — sequences multiple treatments into a clinically-ordered plan.
Stub in slice A; real implementation in slice F.
"""

from __future__ import annotations

from app.agents.verticals.dental_services.state import DentalAgentState


async def treatment_planner_agent(state: DentalAgentState) -> DentalAgentState:
    state["response"] = (
        "I can sequence multiple treatments into a coherent plan (e.g. cleaning → "
        "whitening → bonding). The planner lands next."
    )
    state.setdefault("treatment_stack", None)
    state.setdefault("items", [])
    state.setdefault("cta_links", [])
    return state
