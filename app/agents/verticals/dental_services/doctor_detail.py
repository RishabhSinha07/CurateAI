"""Doctor detail — deep Q&A on a doctor previously surfaced by doctor_search.

Reads extracted_context["shown_doctors"] (populated by doctor_search.py) and
uses the LLM to:
  1. Pick which doctor the user is asking about — by ordinal ("first",
     "second", "the senior one"), by name ("Dr Faiz"), or by attribute
     ("the 12-year one", "the one in Bangalore").
  2. Answer the user's question using ONLY that doctor's record. If the
     record doesn't carry the asked-about field (e.g. "what's their
     availability" when we don't track schedules), say so plainly and
     point at the consultation / WhatsApp channels.

Mirrors service_detail.py in shape — same persona, same grounding
discipline.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agents.shared.llm import get_bedrock_llm
from app.agents.verticals.dental_services.knowledge import PERSONA_SYSTEM_PROMPT
from app.agents.verticals.dental_services.state import DentalAgentState

logger = logging.getLogger(__name__)


class DoctorDetailResponse(BaseModel):
    doctor_id: str = Field(
        description=(
            "The id (UUID) of the doctor the user is asking about. "
            "MUST be one of the ids in the shown_doctors list."
        )
    )
    answer: str = Field(
        description=(
            "Answer the user's specific question using the doctor's record. "
            "2-4 sentences. Plain language. Never invent facts. If the "
            "record doesn't cover the question, say so and suggest the user "
            "reach out via consultation or WhatsApp."
        )
    )
    suggested_replies: list[str] = Field(default_factory=list)


def _format_doctor(idx: int, d: dict[str, Any]) -> str:
    parts = [
        f"- index: {idx + 1}",
        f"  id: {d.get('id')}",
        f"  name: {d.get('full_name')}",
        f"  gender: {d.get('gender') or 'unspecified'}",
        f"  city: {d.get('city') or 'unspecified'}",
        f"  experience_years: {d.get('experience_years')}",
        f"  specializations: {', '.join(d.get('specializations') or []) or 'unspecified'}",
        f"  credentials: {', '.join(d.get('credentials') or []) or 'unspecified'}",
        f"  languages: {', '.join(d.get('languages') or []) or 'unspecified'}",
    ]
    if d.get("cases_done"):
        parts.append(f"  cases_done: {d['cases_done']}")
    if d.get("tier"):
        parts.append(f"  tier: {d['tier']}")
    if d.get("rating"):
        parts.append(f"  rating: {d['rating']}")
    if d.get("bio"):
        parts.append(f"  bio: {d['bio']}")
    return "\n".join(parts)


def _doctor_to_item(d: dict[str, Any]) -> dict[str, Any]:
    """Map the persisted shown_doctors record back to a ChatItem dict so
    the same DoctorCard renders. Mirrors doctor_search's _doctor_to_item."""
    badges: list[str] = []
    if d.get("gender"):
        badges.append({"F": "Female", "M": "Male"}.get(d["gender"].upper(), d["gender"]))
    if d.get("experience_years"):
        badges.append(f"{d['experience_years']}+ yrs")
    badges.extend(d.get("credentials") or [])

    attrs = {
        "city": d.get("city"),
        "experience_years": d.get("experience_years"),
        "specializations": list(d.get("specializations") or []),
        "credentials": list(d.get("credentials") or []),
        "languages": list(d.get("languages") or []),
        "cases_done": d.get("cases_done"),
        "tier": d.get("tier"),
        "detail": True,  # render full bio variant
    }

    subtitle_bits: list[str] = []
    if d.get("specializations"):
        subtitle_bits.append(", ".join(s.title() for s in d["specializations"]))
    if d.get("city"):
        subtitle_bits.append(d["city"])
    subtitle = " · ".join(subtitle_bits) or None

    return {
        "type": "doctor",
        "id": str(d.get("id") or ""),
        "title": d.get("full_name") or "",
        "subtitle": subtitle,
        "price": None,
        "currency": "INR",
        "image_url": None,
        "url": d.get("bio_url"),
        "description": d.get("bio"),
        "badges": badges,
        "attributes": attrs,
    }


async def doctor_detail_agent(state: DentalAgentState) -> DentalAgentState:
    user_message = state.get("user_message", "").strip()
    ctx = state.get("extracted_context") or {}
    shown_doctors: list[dict[str, Any]] = list(ctx.get("shown_doctors") or [])

    if not shown_doctors:
        # No prior doctor context — fall through gracefully (shouldn't
        # happen if refinement routed us here, but defensive).
        state["response"] = (
            "I don't have a specific doctor in mind from our conversation yet. "
            "Tell me your city + what treatment you're after and I'll find one."
        )
        state["items"] = []
        return state

    catalog_block = "\n\n".join(_format_doctor(i, d) for i, d in enumerate(shown_doctors))

    prompt = f"""{PERSONA_SYSTEM_PROMPT}

The patient is following up on the doctors we showed them most recently and asked:
"{user_message}"

Pick the doctor they're asking about and answer using ONLY that doctor's data
below. The patient may reference a doctor by:
  - ordinal: "the first doctor", "second", "third" — match `index` (1-based)
  - name: "Dr Faiz", "Mehta", "Aamir"
  - attribute: "the one in Bangalore", "the senior one", "the 12-year one"

If the patient's reference is ambiguous, pick the first one (index 1) and
acknowledge that in the answer.

Doctors shown (in the order they appeared on screen):

{catalog_block}

Rules:
- `doctor_id` must be EXACTLY one of the id values above (UUIDs).
- Answer in 2-4 sentences. Plain language.
- Reference specifics from the record: name, specializations, credentials,
  experience years, languages, cases_done, tier, bio excerpts.
- If the question asks about a field NOT in the record (availability,
  exact appointment slot, current cost for a specific procedure with this
  doctor), say so honestly and suggest the user reach out via the
  Book Free Consultation or WhatsApp options.
- suggested_replies: 2-3 short follow-ups under 50 chars.
"""

    model = get_bedrock_llm(structured_output_schema=DoctorDetailResponse)
    try:
        result: DoctorDetailResponse = await model.ainvoke(prompt)
    except Exception as e:
        logger.warning("doctor_detail LLM failed: %s", e)
        first = shown_doctors[0]
        state["response"] = (
            f"Here's a recap of **{first.get('full_name')}**: "
            f"{', '.join(first.get('specializations') or []) or 'general dentistry'}"
            f"{(' · ' + str(first.get('experience_years')) + '+ yrs') if first.get('experience_years') else ''}. "
            f"A consultation is the best way to get specific answers about scheduling or pricing."
        )
        state["items"] = [_doctor_to_item(first)]
        return state

    picked = next(
        (d for d in shown_doctors if str(d.get("id")) == result.doctor_id),
        shown_doctors[0],
    )

    state["response"] = result.answer
    state["items"] = [_doctor_to_item(picked)]
    cta_links: list[dict[str, Any]] = []
    if picked.get("bio_url"):
        cta_links.append({
            "label": f"View {picked.get('full_name')}'s profile",
            "url": picked["bio_url"],
            "kind": "secondary",
        })
    state["cta_links"] = cta_links
    state["suggested_replies"] = result.suggested_replies or []
    # Doctor-detail turns preserve completed status so a subsequent
    # refinement turn can still see shown_doctors (we don't clear it).
    state.setdefault("status", "completed")
    return state
