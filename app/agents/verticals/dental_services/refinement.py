"""Refinement node — post-completion follow-ups.

When the prior turn completed (status=completed), an incoming message
could be:
  - asking about a shown treatment → service_detail
  - asking for cheaper / different / alternative options → router (re-classify)
  - changing topic entirely → router (re-classify)

Phase 2 implementation: lightweight LLM detector that picks one of two
outcomes (service_detail vs route-to-router). Falls back to router on any
failure.
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
            "One of: 'service_detail' (user is asking about a treatment we "
            "just showed), 'new_topic' (anything else — re-classify via router)."
        )
    )


async def refinement_agent(state: DentalAgentState) -> DentalAgentState:
    user_message = state.get("user_message", "").strip()
    ctx = state.get("extracted_context") or {}
    shown_ids: list[str] = list(ctx.get("shown_treatments") or [])

    # No prior recommendations → can only re-classify.
    if not shown_ids:
        state["next_agent"] = "router"
        return state

    prompt = (
        "A dental chatbot conversation just completed a recommendation. The patient "
        "now sent a new message. Decide whether they're following up on the SAME "
        "treatments we just showed, or asking about something new.\n\n"
        f"Previously shown treatment ids: {shown_ids}\n"
        f"New message: \"{user_message}\"\n\n"
        "If the new message references one of the shown treatments specifically "
        "(by name, pronoun, or description) — answer 'service_detail'. Otherwise "
        "answer 'new_topic'."
    )

    model = get_bedrock_llm(structured_output_schema=RefinementResponse)
    try:
        result: RefinementResponse = await model.ainvoke(prompt)
    except Exception as e:
        logger.warning("refinement LLM failed: %s", e)
        state["next_agent"] = "router"
        return state

    if result.decision == "service_detail":
        state["next_agent"] = "service_detail"
        state["intent_type"] = "service_detail"
    else:
        state["next_agent"] = "router"
    return state
