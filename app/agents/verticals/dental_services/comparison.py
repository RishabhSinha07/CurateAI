"""Comparison node — side-by-side comparison of two (or more) treatments
weighted by the patient's stated criteria.

Phase 2: emit the comparison as a markdown table in the response (the
chat bubble already renders markdown). When the UI / widget gain a
dedicated `type: "comparison"` card we can move the table into
ChatItem.attributes.
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


# How many criteria rows we ask the LLM to produce.
MAX_CRITERIA = 5


class ComparisonRow(BaseModel):
    criterion: str = Field(description="One word/phrase: Timeline, Cost, Visibility, etc.")
    cells: list[str] = Field(description="One short cell per treatment, same order as treatment_names")
    winner_index: int | None = Field(
        default=None,
        description="0-based index of the winning option for this criterion, or null if tied",
    )


class ComparisonResponse(BaseModel):
    treatment_ids: list[str] = Field(
        description="2-3 treatment ids being compared (must come from the catalog)"
    )
    treatment_names: list[str] = Field(description="Display names, same order as treatment_ids")
    rows: list[ComparisonRow] = Field(description="3-5 comparison rows")
    recommendation_id: str = Field(description="The treatment_id you'd recommend for THIS patient")
    rationale: str = Field(description="2-3 sentence rationale referencing the patient's situation")
    suggested_replies: list[str] = Field(default_factory=list)


def _format_catalog() -> str:
    lines = []
    for t in TREATMENTS.values():
        lines.append(
            f"- id={t['id']} | {t['name']} ({t['category']}) | "
            f"duration={t['typical_duration']} | price={t['price_band']} | "
            f"pros={', '.join(t['pros'][:2])} | cons={', '.join(t['cons'][:2])}"
        )
    return "\n".join(lines)


def _build_prompt(user_message: str, filled_slots: dict[str, Any]) -> str:
    slot_lines = "\n".join(f"  - {k}: {v}" for k, v in filled_slots.items()) or "  (none)"
    return f"""{PERSONA_SYSTEM_PROMPT}

The patient asked for a comparison: "{user_message}"

What we know about them (may be empty if they just opened with the comparison):
{slot_lines}

Available treatments in the catalog:
{_format_catalog()}

Task:
1. Identify the 2 or 3 treatments the patient is comparing (or that best
   answer the question). Use their catalog ids exactly.
2. Pick 3-5 criteria that matter for THIS patient. Common ones: Timeline,
   Cost, Visibility, Effort/Comfort, Durability. Tailor to their slots.
3. For each criterion, write a short cell per treatment (≤ 15 words).
   If one option is clearly better for the patient on this criterion, set
   winner_index to its position (0-based). Otherwise leave winner_index null.
4. recommendation_id: pick the treatment that best fits the patient's
   specific situation. Must be one of the treatments you compared.
5. rationale: 2-3 sentences. Calm and non-pushy. Reference the patient's
   timeline or budget if they mentioned one.
6. suggested_replies: 2-3 short follow-ups under 50 chars.
"""


def _render_markdown_table(result: ComparisonResponse) -> str:
    if not result.treatment_names or not result.rows:
        return ""
    header = "| Criterion | " + " | ".join(result.treatment_names) + " |"
    divider = "|" + ("---|" * (1 + len(result.treatment_names)))
    body_rows = []
    for row in result.rows:
        # Pad cells in case the LLM returned fewer than treatments
        cells = list(row.cells) + [""] * (len(result.treatment_names) - len(row.cells))
        cells = cells[: len(result.treatment_names)]
        if row.winner_index is not None and 0 <= row.winner_index < len(cells):
            cells[row.winner_index] = f"**{cells[row.winner_index]}** ✓"
        body_rows.append(f"| {row.criterion} | " + " | ".join(cells) + " |")
    return "\n".join([header, divider] + body_rows)


def _treatment_to_item(t: Treatment, *, detail: bool = False) -> dict[str, Any]:
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
    }
    if detail:
        attrs["detail"] = True
    return {
        "type": "service",
        "id": t["id"],
        "title": t["name"],
        "subtitle": t["category"].title(),
        "price": None,
        "currency": "INR",
        "image_url": None,
        "url": f"https://www.dezy.com/treatments/{t['url_slug']}",
        "description": t.get("short"),
        "badges": badges,
        "attributes": attrs,
    }


async def comparison_agent(state: DentalAgentState) -> DentalAgentState:
    user_message = state.get("user_message", "")
    filled = state.get("filled_slots") or {}

    model = get_bedrock_llm(structured_output_schema=ComparisonResponse)
    try:
        result: ComparisonResponse = await model.ainvoke(
            _build_prompt(user_message, filled)
        )
    except Exception as e:
        logger.warning("comparison LLM failed: %s", e)
        state["response"] = (
            "I can compare treatments side-by-side. Could you tell me which two "
            "you'd like to compare — for example, aligners vs braces, or implant vs bridge?"
        )
        state["items"] = []
        return state

    valid_ids = [tid for tid in result.treatment_ids if tid in TREATMENTS]
    if len(valid_ids) < 2:
        state["response"] = (
            "I wasn't sure which treatments you'd like to compare. Could you tell me, "
            "for example: 'aligners vs metal braces' or 'implant vs bridge'?"
        )
        state["items"] = []
        return state

    # Build the visible markdown answer:
    md_table = _render_markdown_table(result)
    rec = TREATMENTS.get(result.recommendation_id)
    rec_line = ""
    if rec is not None:
        rec_line = f"\n\n**For your situation:** {rec['name']} — {result.rationale}"

    response_md = ""
    if md_table:
        response_md = f"Here's how they stack up:\n\n{md_table}{rec_line}"
    else:
        response_md = result.rationale

    state["response"] = response_md

    # Surface the 2 (or 3) compared treatments as service items so the patient
    # can click through to either treatment page.
    items: list[dict[str, Any]] = []
    for tid in valid_ids[:3]:
        items.append(_treatment_to_item(TREATMENTS[tid], detail=(tid == result.recommendation_id)))
    state["items"] = items

    # CTAs: a Learn-more link for the recommended treatment + Book (added by safety).
    cta_links: list[dict[str, Any]] = []
    if rec is not None:
        cta_links.append({
            "label": f"Learn more about {rec['name']}",
            "url": f"https://www.dezy.com/treatments/{rec['url_slug']}",
            "kind": "secondary",
        })
    state["cta_links"] = cta_links

    state["suggested_replies"] = result.suggested_replies or []
    state["comparison_payload"] = {
        "treatment_ids": valid_ids,
        "rows": [r.model_dump() for r in result.rows],
        "recommendation_id": result.recommendation_id,
    }
    state["status"] = "completed"
    return state
