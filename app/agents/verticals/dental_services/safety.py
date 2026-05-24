"""Dental safety node — clinical-tone wrapper for the final response.

Takes whatever the upstream node assembled (response text, items, ctas) and:
  - ensures the response is non-empty and uses the Dezy persona
  - appends a generic clinical disclaimer once
  - always offers a Book Consultation CTA as a fallback if nothing else
  - guarantees state.status is set
"""

from __future__ import annotations

import logging

from app.agents.verticals.dental_services.knowledge import (
    BOOK_CONSULT_CTA,
    DEFAULT_DISCLAIMER,
)
from app.agents.verticals.dental_services.state import DentalAgentState

logger = logging.getLogger(__name__)


def _has_disclaimer(text: str) -> bool:
    lower = text.lower()
    return "not a substitute" in lower or "informational only" in lower


def _has_book_cta(ctas: list[dict]) -> bool:
    return any(c.get("url") == BOOK_CONSULT_CTA["url"] for c in ctas)


async def safety_agent(state: DentalAgentState) -> DentalAgentState:
    response = state.get("response") or ""

    if not response.strip():
        response = (
            "I'm sorry — I wasn't able to put together a clear answer just now. "
            "The fastest way to get tailored guidance is a free consultation with a Dezy clinician."
        )

    # Append disclaimer exactly once.
    if not _has_disclaimer(response):
        response = f"{response.rstrip()}\n\n_{DEFAULT_DISCLAIMER}_"

    state["response"] = response

    # Always provide at least one CTA — Book Consultation is the universal one.
    ctas = list(state.get("cta_links") or [])
    if not _has_book_cta(ctas):
        ctas.append(BOOK_CONSULT_CTA)
    state["cta_links"] = ctas

    state.setdefault("status", "completed")
    state.setdefault("items", [])
    state.setdefault("suggested_replies", [])
    return state
