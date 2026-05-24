"""Refinement node — post-completion follow-ups.

When the prior turn completed (status=completed), an incoming message could be:
  - asking about a treatment we just showed → `service_detail`
  - asking about a doctor we just listed → `doctor_detail`
  - asking for cheaper / different / alternative options → `router` (re-classify)
  - changing topic entirely → `router` (re-classify)

The decision is LLM-driven when there's prior context to choose between.
Falls back to `router` on any failure.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.agents.shared.llm import get_bedrock_llm
from app.agents.verticals.dental_services.state import DentalAgentState

logger = logging.getLogger(__name__)


class RefinementResponse(BaseModel):
    decision: str = Field(
        description=(
            "One of: "
            "'service_detail' (asking about a treatment we just showed), "
            "'doctor_detail' (asking about a doctor we just listed), "
            "'new_topic' (anything else — re-classify via router)."
        )
    )


async def refinement_agent(state: DentalAgentState) -> DentalAgentState:
    user_message = state.get("user_message", "").strip()
    ctx = state.get("extracted_context") or {}
    shown_treatments: list[str] = list(ctx.get("shown_treatments") or [])
    shown_doctors_raw = list(ctx.get("shown_doctors") or [])
    # Reduced view for the prompt — we don't need to flood it with full bios.
    shown_doctors_brief = [
        {
            "id": d.get("id"),
            "name": d.get("full_name"),
            "city": d.get("city"),
            "specs": d.get("specializations"),
        }
        for d in shown_doctors_raw
    ]

    # If we have neither context, the only sensible move is fresh classification.
    if not shown_treatments and not shown_doctors_brief:
        state["next_agent"] = "router"
        return state

    prompt = f"""A dental chatbot conversation just completed a previous turn. The patient
sent a new message. Decide whether they're following up on what we just
showed them or asking about something new.

Previously shown treatment ids: {shown_treatments or '(none)'}
Previously shown doctors: {shown_doctors_brief or '(none)'}

New patient message: "{user_message}"

Choose ONE:
- 'service_detail' — message references one of the shown treatments
  (by name, pronoun like "the bridge option", or asking about its
  procedure / price / duration / pain / recovery)
- 'doctor_detail' — message references one of the shown doctors
  (by ordinal "first/second/third", by name "Dr Faiz", or asking about
  their experience / specialization / credentials / languages / cases)
- 'new_topic' — message is about something else (a different concern,
  a new question that isn't about the shown items, a comparison, etc.)
"""

    model = get_bedrock_llm(structured_output_schema=RefinementResponse)
    try:
        result: RefinementResponse = await model.ainvoke(prompt)
    except Exception as e:
        logger.warning("refinement LLM failed: %s", e)
        state["next_agent"] = "router"
        return state

    decision = result.decision
    # Guard against the LLM choosing a branch we don't have context for.
    if decision == "service_detail" and not shown_treatments:
        decision = "doctor_detail" if shown_doctors_brief else "router"
    if decision == "doctor_detail" and not shown_doctors_brief:
        decision = "service_detail" if shown_treatments else "router"

    if decision == "service_detail":
        state["next_agent"] = "service_detail"
        state["intent_type"] = "service_detail"
    elif decision == "doctor_detail":
        state["next_agent"] = "doctor_detail"
        state["intent_type"] = "doctor_detail"
    else:
        state["next_agent"] = "router"
    return state
