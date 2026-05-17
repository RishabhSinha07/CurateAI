"""Service detail — deep Q&A on a specific treatment the patient was just shown.

Reads extracted_context["shown_treatments"] (a list of treatment ids set
by the recommender / comparison / planner on the previous turn) and uses
the LLM to match the user's reference ("tell me more about the bridge")
to one of them, then answers using the treatment's record + persona.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agents.shared.llm import get_bedrock_llm
from app.agents.verticals.dental_services.knowledge import (
    PERSONA_SYSTEM_PROMPT,
    TREATMENTS,
    Treatment,
)
from app.agents.verticals.dental_services.state import DentalAgentState

logger = logging.getLogger(__name__)


class ServiceDetailResponse(BaseModel):
    treatment_id: str = Field(description="The catalog id the user was asking about (must be from the shown set)")
    answer: str = Field(
        description=(
            "Answer the user's specific question using the treatment's data. "
            "Calm and plain language. 2-4 sentences. Never invent facts not in "
            "the record."
        )
    )
    suggested_replies: list[str] = Field(default_factory=list)


def _format_treatment(t: Treatment) -> str:
    return (
        f"- id: {t['id']}\n"
        f"  name: {t['name']}\n"
        f"  category: {t['category']}\n"
        f"  short: {t['short']}\n"
        f"  typical_duration: {t['typical_duration']}\n"
        f"  recovery: {t['recovery']}\n"
        f"  price_band: {t['price_band']}\n"
        f"  emi_eligible: {t['emi_eligible']}\n"
        f"  pros: {', '.join(t['pros'])}\n"
        f"  cons: {', '.join(t['cons'])}"
    )


def _treatment_to_detail_item(t: Treatment) -> dict[str, Any]:
    badges = [t["category"]]
    if t.get("emi_eligible"):
        badges.append("EMI available")
    return {
        "type": "service",
        "id": t["id"],
        "title": t["name"],
        "subtitle": t["category"].title(),
        "price": None,
        "currency": "INR",
        "image_url": None,
        "url": f"https://www.dezy.com{t['url_path']}",
        "description": t.get("short"),
        "badges": badges,
        "attributes": {
            "detail": True,
            "typical_duration": t["typical_duration"],
            "recovery": t["recovery"],
            "price_band": t["price_band"],
            "emi_eligible": t["emi_eligible"],
            "pros": t["pros"],
            "cons": t["cons"],
            "alternative_to": t["alternative_to"],
            "precedes": t["precedes"],
        },
    }


async def service_detail_agent(state: DentalAgentState) -> DentalAgentState:
    user_message = state.get("user_message", "").strip()
    ctx = state.get("extracted_context") or {}
    shown_ids: list[str] = list(ctx.get("shown_treatments") or [])

    # If nothing was shown previously, we can't ground service-detail Q&A.
    # Drop to a clarifying response.
    if not shown_ids:
        state["response"] = (
            "I don't have a specific treatment in mind from our conversation yet. "
            "Could you tell me which one you're asking about — for example, implant, "
            "aligners, whitening — and I'll go into the details."
        )
        state["items"] = []
        return state

    shown_treatments = [TREATMENTS[tid] for tid in shown_ids if tid in TREATMENTS]
    catalog_block = "\n\n".join(_format_treatment(t) for t in shown_treatments)

    prompt = f"""{PERSONA_SYSTEM_PROMPT}

The patient is following up on a treatment we discussed earlier and asked:
"{user_message}"

These are the treatments we showed them most recently — pick the ONE they
are asking about and answer their question using ONLY this data:

{catalog_block}

Rules:
- treatment_id must be exactly one of the ids shown.
- Answer in 2-4 sentences. Plain language. Reference specifics like
  duration, recovery, price band when relevant.
- Never invent facts. If the data doesn't cover their question (e.g. they
  asked about pain and pain isn't in the data), say so and suggest a
  consultation.
- suggested_replies: 2-3 short follow-ups under 50 chars.
"""

    model = get_bedrock_llm(structured_output_schema=ServiceDetailResponse)
    try:
        result: ServiceDetailResponse = await model.ainvoke(prompt)
    except Exception as e:
        logger.warning("service_detail LLM failed: %s", e)
        # Fall back to a generic "tell me more about" using the first shown treatment.
        first = shown_treatments[0]
        state["response"] = (
            f"Here's a recap of **{first['name']}**: {first['short']} "
            f"Typical duration: {first['typical_duration']}. "
            f"Price: {first['price_band']}. A clinician can answer specific questions during a free consult."
        )
        state["items"] = [_treatment_to_detail_item(first)]
        return state

    picked_id = result.treatment_id if result.treatment_id in TREATMENTS else shown_ids[0]
    picked = TREATMENTS[picked_id]

    state["response"] = result.answer
    state["items"] = [_treatment_to_detail_item(picked)]
    state["cta_links"] = [
        {
            "label": f"Learn more about {picked['name']}",
            "url": f"https://www.dezy.com{picked['url_path']}",
            "kind": "secondary",
        },
    ]
    state["suggested_replies"] = result.suggested_replies or []
    # Service-detail turns don't end the multi-turn slot loop — preserve
    # the existing status so the previous flow can resume if needed.
    state.setdefault("status", "completed")
    return state
