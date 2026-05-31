"""Doctor search — multi-attribute filter over the doctors table.

The router has already extracted state["doctor_filters"] = {gender, city,
specialization, max_price_inr}. We translate that into a SQL filter,
render matches as type="doctor" ChatItems, and write a short response.

If no doctors match the strict filters, we relax (drop the strictest) and
note that in the response. If nothing matches at all, fall back to a
Book Consultation suggestion.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.shared.llm import get_bedrock_llm
from app.agents.verticals.dental_services.knowledge import PERSONA_SYSTEM_PROMPT
from app.agents.verticals.dental_services.state import DentalAgentState
from app.db.repositories.dental.doctor import DoctorRepository

logger = logging.getLogger(__name__)


class DoctorBlurb(BaseModel):
    doctor_id: str = Field(description="The id of the doctor this blurb is for.")
    blurb: str = Field(
        description=(
            "One short sentence (max ~20 words) on why this doctor is a fit, "
            "grounded strictly in the bio/credentials/experience/cases/rating "
            "provided. No invented facts, no superlatives like 'best'."
        )
    )


class CuratedDoctorResponse(BaseModel):
    lead: str = Field(
        description=(
            "Warm, 1-2 sentence opener in Dezy's voice that acknowledges what "
            "the patient asked for (city, procedure, anxiety if present) and "
            "introduces the matches. No bullet list. No doctor names here."
        )
    )
    top_pick_id: str = Field(
        description="The id of the doctor most worth highlighting first."
    )
    top_pick_reason: str = Field(
        description=(
            "1-2 sentences explaining why this clinician is highlighted "
            "(experience, case volume, specialization fit). Grounded in the "
            "data provided. No outcome guarantees."
        )
    )
    blurbs: list[DoctorBlurb] = Field(
        default_factory=list,
        description="One blurb for each remaining doctor (excluding the top pick).",
    )


def _doctor_to_item(d: Any) -> dict[str, Any]:
    badges: list[str] = []
    if d.gender:
        badges.append({"F": "Female", "M": "Male"}.get(d.gender.upper(), d.gender))
    if d.experience_years:
        badges.append(f"{d.experience_years}+ yrs")
    badges.extend((d.credentials or []))

    attrs: dict[str, Any] = {
        "city": d.city,
        "experience_years": d.experience_years,
        "specializations": list(d.specializations or []),
        "credentials": list(d.credentials or []),
        "languages": list(d.languages or []),
        "clinic_id": str(d.clinic_id) if d.clinic_id else None,
        "detail": False,
    }

    subtitle_bits: list[str] = []
    if d.specializations:
        subtitle_bits.append(", ".join(s.title() for s in d.specializations))
    if d.city:
        subtitle_bits.append(d.city)
    subtitle = " · ".join(subtitle_bits) or None

    return {
        "type": "doctor",
        "id": str(d.id),
        "title": d.full_name,
        "subtitle": subtitle,
        "price": None,
        "currency": "INR",
        "image_url": d.photo_url,
        "url": d.bio_url,
        "description": (d.bio or "")[:240] or None,
        "badges": badges,
        "attributes": attrs,
    }


def _doctor_profile_for_llm(d: Any) -> str:
    attrs = d.attributes or {}
    parts = [f"id: {d.id}", f"name: {d.full_name}"]
    if d.city:
        parts.append(f"city: {d.city}")
    if d.specializations:
        parts.append(f"specializations: {', '.join(d.specializations)}")
    if d.credentials:
        parts.append(f"credentials: {', '.join(d.credentials)}")
    if d.experience_years:
        parts.append(f"experience_years: {d.experience_years}")
    if d.languages:
        parts.append(f"languages: {', '.join(d.languages)}")
    if attrs.get("cases_done"):
        parts.append(f"cases_done: {attrs['cases_done']}")
    if attrs.get("rating"):
        parts.append(f"rating: {attrs['rating']}")
    if attrs.get("tier"):
        parts.append(f"tier: {attrs['tier']}")
    if d.bio:
        parts.append(f"bio: {d.bio.strip()[:400]}")
    return " | ".join(parts)


def _build_curation_prompt(
    user_message: str,
    described: str,
    relaxed: bool,
    doctors: list[Any],
) -> str:
    profiles = "\n\n".join(_doctor_profile_for_llm(d) for d in doctors)
    relax_note = (
        "We couldn't find an exact city match, so these are matching clinicians "
        "in other locations. Acknowledge this gently in the lead.\n\n"
        if relaxed
        else ""
    )
    return f"""{PERSONA_SYSTEM_PROMPT}

The patient asked: "{user_message or described}"
They're looking for: {described}.

{relax_note}Below are the candidate Dezy clinicians (only these are real — do not invent
others or invent facts about them). Each is one line of `key: value | ...`.

CANDIDATES:
{profiles}

Write a curated response with:
- `lead`: a warm 1-2 sentence opener (no doctor names, no bullets).
- `top_pick_id`: pick the strongest fit using experience_years, cases_done,
  rating, tier, and specialization match. Return its id verbatim.
- `top_pick_reason`: 1-2 sentences, grounded in the candidate's actual data.
- `blurbs`: one entry per remaining candidate (exclude the top pick), each
  with its `doctor_id` and a one-sentence blurb (~20 words) grounded in
  that candidate's data.

Rules:
- Never invent credentials, experience, ratings, or case counts.
- Never claim guaranteed outcomes or use words like "best" / "top-rated".
- Plain language. No jargon unless you explain it.
"""


def _format_curated_response(
    curated: CuratedDoctorResponse,
    items_by_id: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
) -> str:
    top_id = curated.top_pick_id
    top_item = items_by_id.get(top_id)
    if top_item is None:
        # LLM returned an id we didn't ship — fall back to first item.
        top_item = items[0]
        top_id = top_item["id"]

    lines = [curated.lead.strip(), ""]
    top_subtitle = top_item.get("subtitle") or ""
    lines.append(f"★ **{top_item['title']}**{(' — ' + top_subtitle) if top_subtitle else ''}")
    if curated.top_pick_reason.strip():
        lines.append(curated.top_pick_reason.strip())

    blurbs_by_id = {b.doctor_id: b.blurb.strip() for b in curated.blurbs if b.blurb}
    remaining = [it for it in items if it["id"] != top_id]
    if remaining:
        lines.append("")
        lines.append("Also worth considering:")
        for it in remaining:
            blurb = blurbs_by_id.get(it["id"])
            subtitle = it.get("subtitle") or ""
            head = f"- **{it['title']}**" + (f" — {subtitle}" if subtitle else "")
            if blurb:
                lines.append(f"{head}. {blurb}")
            else:
                lines.append(head)

    return "\n".join(lines)


def _describe_filters(filters: dict[str, Any]) -> str:
    parts: list[str] = []
    if filters.get("gender") == "F":
        parts.append("female")
    elif filters.get("gender") == "M":
        parts.append("male")
    if filters.get("specialization"):
        parts.append(f"{filters['specialization']} specialist")
    else:
        parts.append("dentist")
    if filters.get("city"):
        parts.append(f"in {filters['city']}")
    if filters.get("max_price_inr"):
        parts.append(f"under ₹{filters['max_price_inr']:,}")
    return " ".join(parts).strip() or "doctor"


async def doctor_search_agent(state: DentalAgentState, db: AsyncSession) -> DentalAgentState:
    filters = dict(state.get("doctor_filters") or {})
    tenant_id = state.get("tenant_id")
    if tenant_id is None:
        state["response"] = (
            "Could you share your city and what kind of treatment you're looking for? "
            "I'll find a suitable Dezy clinician."
        )
        state["items"] = []
        return state

    repo = DoctorRepository(db)
    matches = await repo.search_by_filters(
        tenant_id=tenant_id,
        gender=filters.get("gender"),
        city=filters.get("city"),
        specialization=filters.get("specialization"),
        limit=5,
    )

    # If strict match returns nothing, try relaxing the city filter once.
    relaxed = False
    if not matches and filters.get("city"):
        matches = await repo.search_by_filters(
            tenant_id=tenant_id,
            gender=filters.get("gender"),
            specialization=filters.get("specialization"),
            limit=5,
        )
        relaxed = bool(matches)

    described = _describe_filters(filters)

    if not matches:
        state["response"] = (
            f"I couldn't find a {described} in our directory right now. The fastest way "
            "is to book a free consultation — we'll match you with a clinician who fits."
        )
        state["items"] = []
        state["cta_links"] = []
        return state

    items = [_doctor_to_item(d) for d in matches]
    state["items"] = items
    state["matched_doctors"] = items

    # Persist the shown doctors so refinement / doctor_detail on the next turn
    # know exactly who the user just saw (and in what order — "first doctor"
    # means matches[0]). We store a compact dict per doctor with all the
    # fields doctor_detail might cite.
    ctx = state.get("extracted_context") or {}
    ctx["shown_doctors"] = [
        {
            "id": str(d.id),
            "slug": d.slug,
            "full_name": d.full_name,
            "city": d.city,
            "gender": d.gender,
            "specializations": list(d.specializations or []),
            "credentials": list(d.credentials or []),
            "languages": list(d.languages or []),
            "experience_years": d.experience_years,
            "bio": d.bio,
            "bio_url": d.bio_url,
            "cases_done": (d.attributes or {}).get("cases_done"),
            "rating": (d.attributes or {}).get("rating"),
            "tier": (d.attributes or {}).get("tier"),
        }
        for d in matches
    ]
    state["extracted_context"] = ctx

    items_by_id = {it["id"]: it for it in items}
    user_message = state.get("user_message", "").strip()
    curated_response_text: str | None = None
    highlighted_doctor = matches[0]

    try:
        model = get_bedrock_llm(structured_output_schema=CuratedDoctorResponse)
        curated: CuratedDoctorResponse = await model.ainvoke(
            _build_curation_prompt(user_message, described, relaxed, matches)
        )
        curated_response_text = _format_curated_response(curated, items_by_id, items)
        for d in matches:
            if str(d.id) == curated.top_pick_id:
                highlighted_doctor = d
                break
    except Exception as e:
        logger.warning("doctor_search curation LLM failed, falling back: %s", e)

    if curated_response_text:
        state["response"] = curated_response_text
    else:
        if relaxed:
            lead = (
                f"I didn't find a {described} exactly, but here are matching clinicians "
                f"at Dezy (in other locations):"
            )
        else:
            lead = f"Here's who I found at Dezy matching: {described}."
        state["response"] = (
            f"{lead}\n\n" + "\n".join(
                f"- **{m['title']}** — {m['subtitle']}" for m in items[:5]
            )
        )

    # Per-doctor CTA so users can jump to a specific bio/book flow.
    cta_links: list[dict[str, Any]] = []
    if highlighted_doctor.bio_url:
        cta_links.append({
            "label": f"View {highlighted_doctor.full_name}'s profile",
            "url": highlighted_doctor.bio_url,
            "kind": "secondary",
        })
    state["cta_links"] = cta_links

    state["suggested_replies"] = [
        "Tell me more about the first doctor",
        "What does an implant cost?",
        "Find a different city",
    ]
    state["status"] = "completed"
    return state
