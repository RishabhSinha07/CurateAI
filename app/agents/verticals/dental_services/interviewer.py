"""Dental interviewer — slot-fills clinical context for treatment_query intent.

Slice A: stub that just routes through to recommender immediately so the
graph topology works end-to-end. Slice B replaces this with real
slot-filling driven by the knowledge module's per-concern slots.
"""

from __future__ import annotations

from app.agents.verticals.dental_services.state import DentalAgentState


async def interviewer_agent(state: DentalAgentState) -> DentalAgentState:
    # Slice A stub — no slot filling yet; route on to initial_treatments
    state["next_agent"] = "initial_treatments"
    state.setdefault("missing_slots", [])
    state.setdefault("filled_slots", {})
    return state
