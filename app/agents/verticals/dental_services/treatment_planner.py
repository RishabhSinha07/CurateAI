"""Treatment planner — sequences multiple treatments into a clinically-
ordered plan (e.g. cleaning → whitening → bonding).

Uses Bedrock to pick the treatments + the order, with the knowledge
module's `precedes` edges providing a soft constraint (cleaning should
precede whitening/veneers/bonding, etc.). Renders the plan as a
numbered markdown list with rationale per step.
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


class PlanStep(BaseModel):
    treatment_id: str = Field(description="Catalog id of the treatment for this step")
    why: str = Field(description="Why this step at this position (≤ 25 words)")
    wait_after: str | None = Field(
        default=None,
        description="What to wait for before the next step (e.g. '1-2 days'), or null",
    )


class PlanResponse(BaseModel):
    steps: list[PlanStep] = Field(description="Ordered list of plan steps, 2-5 items")
    summary: str = Field(description="1-2 sentence framing of the overall plan")
    suggested_replies: list[str] = Field(default_factory=list)


def _format_catalog() -> str:
    lines = []
    for t in TREATMENTS.values():
        precedes = ", ".join(t["precedes"]) or "—"
        lines.append(
            f"- id={t['id']} | {t['name']} ({t['category']}) | "
            f"precedes=[{precedes}] | price={t['price_band']}"
        )
    return "\n".join(lines)


def _build_prompt(user_message: str) -> str:
    return f"""{PERSONA_SYSTEM_PROMPT}

The patient described multiple things they want done: "{user_message}"

Available treatments (with ordering hints — `precedes` means this should come BEFORE):
{_format_catalog()}

Task:
1. Pick the 2-5 treatments that address what the patient asked for.
   Use catalog ids exactly.
2. Order them so any `precedes` constraints are respected. The most common
   case: cleaning should come BEFORE whitening, veneers, or bonding (so the
   surface is clean and the result is even).
3. For each step, give a one-sentence `why` explaining the ordering or
   purpose (≤ 25 words).
4. `wait_after` (optional): if the patient should pause between steps, say
   for how long ("same visit", "1-2 days", "after healing"). Null if no wait.
5. `summary`: 1-2 sentence framing of the overall plan. Calm, non-pushy tone.
6. `suggested_replies`: 2-3 short follow-ups under 50 chars.
"""


def _treatment_to_item(t: Treatment) -> dict[str, Any]:
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
            "typical_duration": t.get("typical_duration"),
            "price_band": t.get("price_band"),
            "emi_eligible": t.get("emi_eligible", False),
        },
    }


def _render_plan_markdown(steps: list[PlanStep], summary: str) -> str:
    lines = [summary.strip(), ""]
    for i, step in enumerate(steps, start=1):
        t = TREATMENTS.get(step.treatment_id)
        if t is None:
            continue
        name = t["name"]
        line = f"**{i}. {name}** — {step.why.strip()}"
        if step.wait_after:
            line += f"  \n_Wait after: {step.wait_after.strip()}_"
        lines.append(line)
    return "\n\n".join(lines)


async def treatment_planner_agent(state: DentalAgentState) -> DentalAgentState:
    user_message = state.get("user_message", "")
    model = get_bedrock_llm(structured_output_schema=PlanResponse)
    try:
        result: PlanResponse = await model.ainvoke(_build_prompt(user_message))
    except Exception as e:
        logger.warning("treatment_planner LLM failed: %s", e)
        state["response"] = (
            "I can sequence multiple treatments into a clinically-sensible plan. "
            "Could you tell me what you'd like done — for example: cleaning, whitening, "
            "and a gap fix?"
        )
        state["items"] = []
        return state

    valid_steps = [s for s in result.steps if s.treatment_id in TREATMENTS]
    if len(valid_steps) < 2:
        state["response"] = (
            "It sounds like you're after one treatment rather than a sequence. "
            "If you'd like a multi-step plan, just list a few things (e.g. 'cleaning, "
            "whitening, fix a small gap') and I'll order them."
        )
        state["items"] = []
        return state

    state["response"] = _render_plan_markdown(valid_steps, result.summary)
    state["items"] = [_treatment_to_item(TREATMENTS[s.treatment_id]) for s in valid_steps]

    # Build the structured plan payload too (for future analytics / refinement).
    state["treatment_stack"] = [s.model_dump() for s in valid_steps]

    state["cta_links"] = [
        {
            "label": "Book all of these together",
            "url": "https://www.dezy.com/new-appointment-flow",
            "kind": "secondary",
        },
    ]
    state["suggested_replies"] = result.suggested_replies or []
    state["status"] = "completed"
    return state
