"""Treatment recommender — synthesizes a treatment recommendation from
filled slots + matched services. Stub in slice A; real logic in slice B.
"""

from __future__ import annotations

from app.agents.verticals.dental_services.state import DentalAgentState


async def treatment_recommender_agent(state: DentalAgentState) -> DentalAgentState:
    state["response"] = (
        "I can help guide you to the right treatment. Phase 2 of this vertical "
        "is being built — the full treatment recommender lands next."
    )
    state.setdefault("items", [])
    state.setdefault("cta_links", [])
    state.setdefault("suggested_replies", [])
    return state
