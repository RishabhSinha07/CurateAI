"""Dental router: classify user intent → pick the next dental node.

The router runs once per turn at the entry point of the dental graph. It
produces:
  - intent_type: which downstream node should handle this turn
  - candidate_concern_id: the patient concern (if any) for the recommender
  - doctor_filters: structured query attrs (for use case 4)
  - escalation triggered: routes straight to fallback (clinical safety)
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agents.shared.llm import get_bedrock_llm
from app.agents.verticals.dental_services.knowledge import (
    CONCERNS,
    find_concern,
    find_escalation,
)
from app.agents.verticals.dental_services.state import DentalAgentState

logger = logging.getLogger(__name__)


VALID_INTENTS = (
    "treatment_query",       # "I have a missing tooth, what should I do?"
    "content_qa",            # "How long is recovery for full mouth implants?"
    "comparison",            # "Aligners vs braces for me?"
    "doctor_search",         # "Female implant specialist in Bangalore"
    "treatment_plan",        # "I want cleaning and whitening, what's the order?"
    "service_detail",        # follow-up Q on a service just shown
    "refinement",            # filter / re-personalise
    "clinical_escalation",   # routes to fallback (handled deterministically too)
    "fallback",              # genuinely out-of-scope
)


class DoctorFilters(BaseModel):
    gender: str | None = Field(default=None, description="'F' | 'M' | 'other' if user explicitly asks")
    city: str | None = Field(default=None, description="City name if user mentions one")
    specialization: str | None = Field(default=None, description="e.g. 'implants', 'orthodontics'")
    max_price_inr: int | None = Field(default=None, description="Upper budget bound in INR if mentioned")


class RouterResponse(BaseModel):
    intent_type: str = Field(
        description=(
            "One of: treatment_query, content_qa, comparison, doctor_search, "
            "treatment_plan, service_detail, refinement, clinical_escalation, fallback"
        )
    )
    confidence: float = Field(ge=0.0, le=1.0)
    candidate_concern_id: str | None = Field(
        default=None,
        description=(
            "If intent is treatment_query and a known concern is mentioned, the concern id. "
            "Valid ids: " + ", ".join(CONCERNS.keys())
        ),
    )
    doctor_filters: DoctorFilters | None = Field(
        default=None,
        description="Set only when intent_type is doctor_search.",
    )
    service_reference: str | None = Field(
        default=None,
        description="If intent is service_detail, the name/phrase referring to a previously shown service.",
    )
    reasoning: str = Field(default="")


PROMPT = """You are the router for Dezy's dental consultation chatbot.
Classify the user's latest message into exactly one intent.

INTENTS:
- treatment_query: User describes a problem or asks what to do about a dental issue.
  Examples: "I have a missing tooth", "what should I do about crooked teeth", "I want to fix yellow teeth"
- content_qa: User asks a procedural/educational question (how long, how painful,
  what's the recovery, what's the process). Examples: "How painful is an implant?",
  "How long is recovery for full mouth implants?", "Is whitening safe?"
- comparison: User asks which option is better, or to compare two treatments.
  Examples: "Aligners vs braces for me", "Should I get an implant or a bridge?"
- doctor_search: User asks for a doctor / clinic with structured attributes
  (gender, city, specialization, budget). Examples: "Female implant specialist
  in Bangalore", "Closest Dezy clinic to me", "Best aligner doctor in Mumbai under ₹50k"
- treatment_plan: User wants multiple treatments and asks about ordering or bundling.
  Examples: "I want cleaning and whitening — what's the order?", "Can I do all of this together?"
- service_detail: User asks a follow-up question about a SPECIFIC service that
  was just recommended/shown to them. Example: "Tell me more about the bridge option you mentioned"
- refinement: User wants to filter or re-personalise prior recommendations.
  Examples: "Cheaper option", "What about the aligner one", "Anything for sensitive teeth?"
- clinical_escalation: User describes acute symptoms, pregnancy + procedure questions,
  cardiac history, bleeding disorders, paediatric (small child) requests. Route to human.
- fallback: Genuinely out of scope (orthopaedics, general medicine, unrelated chit-chat).

ALWAYS pick the SINGLE most appropriate intent. If the message mentions both a problem
and asks how long it takes, the question dominates → content_qa.

If intent is doctor_search, extract structured filters into doctor_filters.
If intent is treatment_query and a known concern is described, set candidate_concern_id
to one of: {concern_ids}.

USER MESSAGE: {user_message}
"""


def get_router_model():
    return get_bedrock_llm(structured_output_schema=RouterResponse)


async def router_agent(state: DentalAgentState) -> DentalAgentState:
    user_message = state.get("user_message", "")

    # --- Deterministic pre-checks ---
    # Clinical escalation: keyword-match before involving the LLM so we don't
    # produce a recommendation when patient safety is at issue.
    trigger = find_escalation(user_message)
    if trigger is not None:
        state["intent_type"] = "clinical_escalation"
        state["next_agent"] = "fallback"
        state["requires_clinical_review"] = True
        state["escalation_reason"] = trigger["reason"]
        return state

    # If we're in an awaiting_slot follow-up, treat short messages as slot answers
    # and route straight to the interviewer.
    pending_q = state.get("pending_slot_question")
    if state.get("status") == "awaiting_slot" and pending_q:
        state["intent_type"] = "treatment_query"
        state["next_agent"] = "interviewer"
        return state

    # --- LLM classification ---
    model = get_router_model()
    try:
        result: RouterResponse = await model.ainvoke(
            PROMPT.format(
                user_message=user_message,
                concern_ids=", ".join(CONCERNS.keys()),
            )
        )
    except Exception as e:
        logger.warning("Dental router LLM call failed: %s", e)
        state["intent_type"] = "fallback"
        state["next_agent"] = "fallback"
        return state

    intent = result.intent_type if result.intent_type in VALID_INTENTS else "fallback"
    state["intent_type"] = intent

    # Pre-classification: if router missed it but a known concern keyword is in the message,
    # promote it for the treatment path.
    if intent in ("treatment_query", "fallback") and not result.candidate_concern_id:
        concern = find_concern(user_message)
        if concern is not None:
            state["candidate_concern_id"] = concern["id"]
            if intent == "fallback":
                intent = "treatment_query"
                state["intent_type"] = intent
    else:
        state["candidate_concern_id"] = result.candidate_concern_id

    if intent == "doctor_search" and result.doctor_filters is not None:
        state["doctor_filters"] = result.doctor_filters.model_dump(exclude_none=True)

    # Map intent → next agent
    state["next_agent"] = _intent_to_node(intent)
    return state


def _intent_to_node(intent: str) -> str:
    return {
        "treatment_query": "interviewer",
        "content_qa": "content_qa",
        "comparison": "comparison",
        "doctor_search": "doctor_search",
        "treatment_plan": "treatment_planner",
        "service_detail": "service_detail",
        "refinement": "refinement",
        "clinical_escalation": "fallback",
        "fallback": "fallback",
    }.get(intent, "fallback")
