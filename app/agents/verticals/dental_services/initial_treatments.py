"""Initial treatments — surface candidate treatments for the identified
concern so the recommender has a working set to choose from.

Phase 2 reads from the knowledge module (CONCERNS[id].treats). Later, this
can be augmented with semantic search over the services table for tenants
that have a full catalog ingested.
"""

from __future__ import annotations

from app.agents.verticals.dental_services.knowledge import treatments_for_concern
from app.agents.verticals.dental_services.state import DentalAgentState


async def initial_treatments_agent(state: DentalAgentState) -> DentalAgentState:
    concern_id = state.get("candidate_concern_id")
    if not concern_id:
        state["candidate_treatments"] = []
        return state

    treatments = treatments_for_concern(concern_id)
    state["candidate_treatments"] = [dict(t) for t in treatments]
    return state
