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

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.verticals.dental_services.state import DentalAgentState
from app.db.repositories.dental.doctor import DoctorRepository

logger = logging.getLogger(__name__)


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
    top = matches[0]
    if top.bio_url:
        cta_links.append({
            "label": f"View {top.full_name}'s profile",
            "url": top.bio_url,
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
