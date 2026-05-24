"""Conversation state for the dental_services vertical.

Field categories:

    Kernel-readable (set by every turn):
        session_id, user_message, tenant_id, tenant_enabled_domains,
        status, extracted_context, response, items, cta_links,
        suggested_replies, vertical_context

    Router output:
        intent_type, next_agent, candidate_concern_id

    Interviewer state:
        missing_slots, filled_slots, optional_slot_hint

    Per-node payloads (populated only by the node that owns them):
        candidate_treatments       — initial_treatments
        recommended_treatment_ids  — treatment_recommender
        doctor_filters             — router (extracted) + doctor_search (uses)
        matched_doctors            — doctor_search
        comparison_payload         — comparison
        treatment_stack            — treatment_planner
        content_citations          — content_qa

    Clinical safety:
        requires_clinical_review, escalation_reason
"""

from __future__ import annotations

import uuid
from typing import Any, TypedDict


class DentalAgentState(TypedDict, total=False):
    # --- Session ---
    session_id: uuid.UUID
    user_message: str
    tenant_id: uuid.UUID | None
    tenant_enabled_domains: list[str]
    previous_response: str | None

    # --- Conversation state ---
    status: str
    extracted_context: dict[str, Any]
    vertical_context: dict[str, Any]
    response: str | None
    items: list[dict[str, Any]]
    cta_links: list[dict[str, Any]]
    suggested_replies: list[str]

    # --- Router output ---
    intent_type: str | None              # treatment_query | content_qa | comparison | doctor_search | treatment_plan | service_detail | refinement | clinical_escalation | fallback
    next_agent: str | None
    candidate_concern_id: str | None     # e.g. "missing_tooth"

    # --- Interviewer state ---
    missing_slots: list[str]
    filled_slots: dict[str, Any]
    optional_slot_hint: str | None
    pending_slot_question: str | None

    # --- Treatment recommendation path ---
    candidate_treatments: list[dict[str, Any]]   # initial_treatments output
    recommended_treatment_ids: list[str]         # final recommendations

    # --- Doctor search ---
    doctor_filters: dict[str, Any] | None        # {gender, city, specialization, max_price_inr}
    matched_doctors: list[dict[str, Any]]

    # --- Comparison ---
    comparison_payload: dict[str, Any] | None    # {criteria: [...], options: [{id, name, scores, notes}]}

    # --- Treatment plan / stack ---
    treatment_stack: list[dict[str, Any]] | None  # [{step, treatment_id, why, wait_after}]

    # --- Content RAG ---
    content_citations: list[dict[str, Any]]      # [{chunk_id, url, snippet}]

    # --- Clinical safety ---
    requires_clinical_review: bool
    escalation_reason: str | None

    # --- Service detail (analog of product_detail) ---
    service_context: dict[str, Any] | None       # full service dict for deep Q&A
