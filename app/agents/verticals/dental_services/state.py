"""Conversation state for the dental_services vertical.

Phase 1 keeps this minimal — only the fields the kernel reads (status,
extracted_context, response) plus per-turn inputs. Phase 2 will extend
with treatment-recommender / doctor-search / content-RAG fields:

    candidate_services, final_services
    doctor_filters, matched_doctors
    comparison_payload
    treatment_stack
    content_citations
    requires_clinical_review
"""

from __future__ import annotations

import uuid
from typing import Any, TypedDict


class DentalAgentState(TypedDict, total=False):
    # Session
    session_id: uuid.UUID
    user_message: str
    tenant_id: uuid.UUID | None
    tenant_enabled_domains: list[str]

    # Conversation state (kernel reads `status` and `extracted_context`)
    status: str
    extracted_context: dict[str, Any]
    previous_response: str | None

    # Vertical-specific context bag (seeded from session.current_domain_slug
    # if present; in dental this will hold things like current_concern,
    # current_doctor_id, last_comparison, etc.)
    vertical_context: dict[str, Any]

    # Final response text (set by the last node in the graph)
    response: str | None

    # Optional fields populated by Phase 2 agents — declared here so the
    # graph and finalize() can reference them without KeyErrors when absent.
    cta_links: list[dict[str, Any]]
    items: list[dict[str, Any]]
    suggested_replies: list[str]
