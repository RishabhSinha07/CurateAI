"""Dental interviewer — slot-fills clinical context for the
treatment-recommendation path.

Conversation shape:
  1. Router classifies intent=treatment_query and (when possible) extracts
     candidate_concern_id.
  2. Interviewer ensures we know the concern. If not, asks a clarifying
     question with the awaiting_slot mechanism.
  3. For the identified concern, asks each typical slot one at a time
     until all are filled, then routes to initial_treatments.

Slot state lives at the top of DentalAgentState but is rehydrated from /
persisted to extracted_context by the vertical adapter so it survives
across turns.
"""

from __future__ import annotations

import logging

from app.agents.verticals.dental_services.knowledge import (
    CONCERNS,
    SLOTS,
    find_concern,
)
from app.agents.verticals.dental_services.state import DentalAgentState

logger = logging.getLogger(__name__)


CONCERN_CLARIFICATION_SLOT = "_concern_clarification"
CONCERN_CLARIFICATION_QUESTION = (
    "Could you tell me a bit more about what's going on? For example: "
    "missing tooth, crooked teeth, tooth pain, yellow teeth, or just a check-up?"
)
CONCERN_CLARIFICATION_REPLIES = [
    "Missing tooth",
    "Crooked teeth",
    "Tooth pain",
    "Yellow teeth",
    "Just a check-up",
]


async def interviewer_agent(state: DentalAgentState) -> DentalAgentState:
    user_message = state.get("user_message", "").strip()
    filled: dict[str, str] = dict(state.get("filled_slots") or {})
    concern_id = state.get("candidate_concern_id")
    pending_slot_id = (state.get("extracted_context") or {}).get("pending_slot_id")

    # --- Step 1: if the prior turn asked a slot question, capture the answer ---
    if pending_slot_id and state.get("status") == "awaiting_slot" and user_message:
        if pending_slot_id == CONCERN_CLARIFICATION_SLOT:
            # Re-identify the concern from this turn's message
            concern = find_concern(user_message)
            if concern is not None:
                concern_id = concern["id"]
                state["candidate_concern_id"] = concern_id
            # If still nothing matched, the loop below will re-ask.
        else:
            filled[pending_slot_id] = user_message

    state["filled_slots"] = filled

    # --- Step 2: ensure we have a concern to anchor recommendations on ---
    if not concern_id:
        _ask(state, CONCERN_CLARIFICATION_SLOT, CONCERN_CLARIFICATION_QUESTION,
             CONCERN_CLARIFICATION_REPLIES)
        return state

    # --- Step 3: find the next unfilled required slot ---
    concern = CONCERNS[concern_id]
    typical_slots = concern.get("typical_slots", [])
    next_slot_id: str | None = None
    for slot_id in typical_slots:
        if slot_id not in filled and slot_id in SLOTS:
            next_slot_id = slot_id
            break

    if next_slot_id is None:
        # All slots filled — route on to initial_treatments → recommender
        state["next_agent"] = "initial_treatments"
        state["missing_slots"] = []
        ctx = state.get("extracted_context") or {}
        ctx.pop("pending_slot_id", None)
        ctx.pop("pending_slot_question", None)
        state["extracted_context"] = ctx
        return state

    # --- Step 4: ask the next question, awaiting the user's reply ---
    slot = SLOTS[next_slot_id]
    _ask(state, next_slot_id, slot["question"], slot.get("quick_replies") or [])
    state["missing_slots"] = [s for s in typical_slots if s not in filled]
    return state


def _ask(state: DentalAgentState, slot_id: str, question: str, replies: list[str]) -> None:
    """Set the state to ask the user a slot question and end the turn."""
    ctx = state.get("extracted_context") or {}
    ctx["pending_slot_id"] = slot_id
    ctx["pending_slot_question"] = question
    state["extracted_context"] = ctx

    state["pending_slot_question"] = question  # convenience for router awaiting-slot check
    state["status"] = "awaiting_slot"
    state["response"] = question
    state["suggested_replies"] = replies
    state["items"] = []
    state["cta_links"] = []
    state["next_agent"] = None  # END the turn
