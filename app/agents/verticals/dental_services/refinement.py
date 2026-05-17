"""Refinement node — post-completion follow-ups (filter, re-personalise, new topic).
Stub in slice A; real implementation in slice G.
"""

from __future__ import annotations

from app.agents.verticals.dental_services.state import DentalAgentState


async def refinement_agent(state: DentalAgentState) -> DentalAgentState:
    # For Slice A: just bounce back to the router for fresh classification.
    state["next_agent"] = "router"
    return state
