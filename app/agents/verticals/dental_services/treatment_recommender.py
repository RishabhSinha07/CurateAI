"""Treatment recommender — pick the best treatment for the patient given
the candidate set + filled slots, and write a calm plain-language
explanation.

Uses Bedrock structured output. Renders the picked treatment + up to two
alternates as ChatItems (type="service"), attaches a "Read more" CTA for
the picked treatment's URL, and offers two follow-up suggested replies.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agents.shared.llm import get_bedrock_llm
from app.agents.verticals.dental_services.knowledge import (
    CONCERNS,
    PERSONA_SYSTEM_PROMPT,
    TREATMENTS,
)
from app.agents.verticals.dental_services.state import DentalAgentState

logger = logging.getLogger(__name__)


class RecommendationResponse(BaseModel):
    primary_treatment_id: str = Field(
        description="The id of the treatment to primarily recommend. Must be one of the candidates provided."
    )
    explanation: str = Field(
        description=(
            "2-4 sentence plain-language explanation directly addressing the patient. "
            "Calm and non-pushy. Acknowledge any anxiety mentioned. Do not diagnose, "
            "do not prescribe medication. Reference the patient's specific situation."
        )
    )
    suggested_replies: list[str] = Field(
        default_factory=list,
        description=(
            "2-3 short follow-up suggestions (e.g. 'How long is recovery?', "
            "'Compare with bridge', 'Find a doctor near me'). Each under 50 chars."
        ),
    )


def _treatment_to_item(t: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    """Map a treatment dict (from knowledge.TREATMENTS) → ChatItem-shaped dict."""
    badges: list[str] = [t["category"]]
    if t.get("emi_eligible"):
        badges.append("EMI available")

    attrs: dict[str, Any] = {
        "typical_duration": t.get("typical_duration"),
        "recovery": t.get("recovery"),
        "price_band": t.get("price_band"),
        "emi_eligible": t.get("emi_eligible", False),
        "pros": t.get("pros") or [],
        "cons": t.get("cons") or [],
        "alternative_to": t.get("alternative_to") or [],
        "precedes": t.get("precedes") or [],
    }
    if detail:
        attrs["detail"] = True

    return {
        "type": "service",
        "id": t["id"],
        "title": t["name"],
        "subtitle": t["category"].title(),
        "price": None,                  # show price_band as a string in attributes
        "currency": "INR",
        "image_url": None,
        "url": f"https://www.dezy.com/treatments/{t['url_slug']}",
        "description": t.get("short"),
        "badges": badges,
        "attributes": attrs,
    }


def _build_prompt(
    concern_id: str,
    candidates: list[dict[str, Any]],
    filled_slots: dict[str, Any],
    user_message: str,
) -> str:
    concern = CONCERNS.get(concern_id, {})
    concern_label = concern.get("display") or concern_id

    candidate_lines = []
    for c in candidates:
        candidate_lines.append(
            f"- id: {c['id']}\n"
            f"  name: {c['name']}\n"
            f"  short: {c.get('short', '')}\n"
            f"  pros: {', '.join(c.get('pros') or [])}\n"
            f"  cons: {', '.join(c.get('cons') or [])}\n"
            f"  price: {c.get('price_band', '')}\n"
            f"  typical_duration: {c.get('typical_duration', '')}\n"
        )
    slot_lines = "\n".join(f"  {k}: {v}" for k, v in filled_slots.items()) or "  (none)"

    return f"""{PERSONA_SYSTEM_PROMPT}

The patient came to Dezy about: {concern_label}

Their original message: "{user_message}"

What we learned from the interview:
{slot_lines}

Candidate treatments (you must pick primary_treatment_id from these):
{''.join(candidate_lines)}

Rules:
- Pick the treatment that best fits the patient's stated preferences and slots.
- Acknowledge their situation in 1 sentence before recommending.
- Keep it under 4 sentences total. Plain language. No jargon.
- Never claim a guaranteed outcome. Defer final decisions to the clinician.
- If they expressed anxiety (e.g. surgery_comfort = "anxious"), gently note that
  the consultation is free and a clinician will walk them through everything.
"""


async def treatment_recommender_agent(state: DentalAgentState) -> DentalAgentState:
    candidates = state.get("candidate_treatments") or []
    if not candidates:
        state["response"] = (
            "I'd love to point you in the right direction. The fastest next step is a "
            "free consultation — a Dezy clinician will look at your case and walk you "
            "through the best options for you."
        )
        state["items"] = []
        state["status"] = "completed"
        return state

    concern_id = state.get("candidate_concern_id") or ""
    filled = state.get("filled_slots") or {}
    user_message = state.get("user_message", "")

    model = get_bedrock_llm(structured_output_schema=RecommendationResponse)
    try:
        result: RecommendationResponse = await model.ainvoke(
            _build_prompt(concern_id, candidates, filled, user_message)
        )
    except Exception as e:
        logger.warning("treatment_recommender LLM failed: %s", e)
        # Fall back: just pick the first candidate, no LLM explanation
        picked = candidates[0]
        result = RecommendationResponse(
            primary_treatment_id=picked["id"],
            explanation=(
                f"Based on what you've shared, **{picked['name']}** is a strong fit. "
                f"{picked.get('short', '')} A Dezy clinician can confirm and walk you through next steps."
            ),
            suggested_replies=["Tell me more", "Find a doctor", "What does it cost?"],
        )

    picked_id = result.primary_treatment_id
    picked = next((c for c in candidates if c["id"] == picked_id), candidates[0])
    alternates = [c for c in candidates if c["id"] != picked["id"]][:2]

    items: list[dict[str, Any]] = [_treatment_to_item(picked, detail=True)]
    items.extend(_treatment_to_item(t) for t in alternates)

    cta_links: list[dict[str, Any]] = [
        {
            "label": f"Learn more about {picked['name']}",
            "url": f"https://www.dezy.com/treatments/{picked['url_slug']}",
            "kind": "secondary",
        }
    ]
    # The safety node appends Book Consultation as a primary CTA.

    state["response"] = result.explanation
    state["items"] = items
    state["cta_links"] = cta_links
    state["suggested_replies"] = result.suggested_replies or []
    state["recommended_treatment_ids"] = [picked["id"]] + [a["id"] for a in alternates]

    # Track shown treatments for future service_detail / refinement turns
    ctx = state.get("extracted_context") or {}
    ctx["shown_treatments"] = [picked["id"]] + [a["id"] for a in alternates]
    state["extracted_context"] = ctx

    state["status"] = "completed"
    return state
