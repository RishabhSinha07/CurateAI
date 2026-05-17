"""Initial treatments — surface 2-3 candidate treatments early in the flow.

Slice A: stub. Slice B populates state["candidate_treatments"] from the
knowledge module (and later from the services table with semantic search).
"""

from __future__ import annotations

from app.agents.verticals.dental_services.state import DentalAgentState


async def initial_treatments_agent(state: DentalAgentState) -> DentalAgentState:
    state.setdefault("candidate_treatments", [])
    return state
