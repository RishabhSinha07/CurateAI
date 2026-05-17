"""Dental fallback / clinical-escalation node.

Handles two cases:
  1. Clinical escalation (state.requires_clinical_review): refuse to recommend
     and offer a human consultation with the specific reason surfaced.
  2. Out-of-scope: explain Dezy's scope and offer a consultation.
"""

from __future__ import annotations

from app.agents.verticals.dental_services.knowledge import BOOK_CONSULT_CTA
from app.agents.verticals.dental_services.state import DentalAgentState


async def fallback_agent(state: DentalAgentState) -> DentalAgentState:
    if state.get("requires_clinical_review"):
        reason = state.get("escalation_reason") or (
            "Your situation needs a clinician's direct attention before we can guide you online."
        )
        state["response"] = (
            f"{reason}\n\n"
            "I won't make a treatment suggestion here — the safest next step is to book a "
            "consultation so a Dezy dentist can assess you in person."
        )
    else:
        state["response"] = (
            "I'm Dezy's dental advisor, so I focus on dental treatments, doctors, and clinics. "
            "If you'd like, I can help you with implants, aligners, whitening, cleanings, or "
            "finding a doctor — just let me know."
        )

    state["cta_links"] = [BOOK_CONSULT_CTA]
    state["items"] = []
    state["status"] = "completed"
    state.setdefault("suggested_replies", [])
    return state
