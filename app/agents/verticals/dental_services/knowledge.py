"""Dental knowledge: concerns, treatments, slots, escalation triggers.

Phase 2 keeps this as plain Python data instead of moving the YAML-based
knowledge-graph infrastructure cross-vertical. The shapes match what the
dental nodes (interviewer, recommender, comparison, planner, fallback)
actually read. If/when this grows, it can be moved to YAML under
app/knowledge/graphs/dental/ behind a dental-scoped loader.
"""

from __future__ import annotations

from typing import TypedDict


# ============================================================================
# Concerns — what a patient may type ("I have a missing tooth", "crowded teeth")
# ============================================================================

class Concern(TypedDict):
    id: str
    display: str
    synonyms: list[str]
    treats: list[str]   # treatment ids this concern is addressed by
    typical_slots: list[str]  # which slot ids to fill before recommending


CONCERNS: dict[str, Concern] = {
    "missing_tooth": {
        "id": "missing_tooth",
        "display": "Missing tooth",
        "synonyms": ["lost tooth", "tooth fell out", "gap from missing tooth", "no tooth"],
        "treats": ["single_implant", "bridge", "denture_partial"],
        "typical_slots": ["permanence_preference"],
    },
    "multiple_missing_teeth": {
        "id": "multiple_missing_teeth",
        "display": "Multiple missing teeth",
        "synonyms": ["several missing teeth", "lost many teeth", "no teeth", "edentulous"],
        "treats": ["full_mouth_implant", "denture_full", "bridge"],
        "typical_slots": ["surgery_comfort"],
    },
    "crowded_teeth": {
        "id": "crowded_teeth",
        "display": "Crowded or crooked teeth",
        "synonyms": ["crooked teeth", "overlapping teeth", "misaligned", "want straighter teeth"],
        "treats": ["clear_aligners", "metal_braces"],
        "typical_slots": ["severity", "timeline_months", "visibility_preference"],
    },
    "gap_between_teeth": {
        "id": "gap_between_teeth",
        "display": "Gap between teeth",
        "synonyms": ["diastema", "small gap", "teeth gap", "space between teeth"],
        "treats": ["clear_aligners", "dental_bonding", "veneers"],
        "typical_slots": ["severity", "timeline_months"],
    },
    "stained_teeth": {
        "id": "stained_teeth",
        "display": "Yellow or stained teeth",
        "synonyms": ["yellow teeth", "discolored teeth", "want whiter smile", "teeth discoloration"],
        "treats": ["teeth_whitening", "veneers", "cleaning"],
        "typical_slots": ["sensitivity_known"],
    },
    "tooth_pain": {
        "id": "tooth_pain",
        "display": "Tooth pain or sensitivity",
        "synonyms": ["toothache", "sensitive teeth", "sharp pain in tooth"],
        "treats": ["consultation", "root_canal", "cleaning"],
        "typical_slots": ["pain_severity", "pain_duration"],
    },
    "general_cleaning": {
        "id": "general_cleaning",
        "display": "Routine cleaning / checkup",
        "synonyms": ["teeth cleaning", "scaling", "polishing", "dental checkup"],
        "treats": ["cleaning", "consultation"],
        "typical_slots": [],
    },
}

# ============================================================================
# Treatments — the catalog of services Dezy provides
# ============================================================================

class Treatment(TypedDict):
    id: str
    name: str
    category: str          # implants | orthodontics | cosmetic | general | restorative
    short: str             # one-line description
    typical_duration: str  # e.g. "1-2 sittings + 3-6 months healing"
    recovery: str          # e.g. "soft food for 2-4 weeks; full recovery 3-6 months"
    price_band: str        # e.g. "₹30k–₹60k per tooth"
    emi_eligible: bool
    url_path: str          # appended to https://www.dezy.com to get the canonical URL
    pros: list[str]
    cons: list[str]
    alternative_to: list[str]  # for comparison node
    precedes: list[str]        # for treatment_planner ordering


TREATMENTS: dict[str, Treatment] = {
    "single_implant": {
        "id": "single_implant",
        "name": "Single Tooth Implant",
        "category": "implants",
        "short": "A titanium post placed in the jawbone, topped with a crown — looks and functions like a natural tooth.",
        "typical_duration": "1-2 sittings; full process 3-6 months including healing",
        "recovery": "soft foods for 2-4 weeks; full recovery 3-6 months",
        "price_band": "₹30,000 – ₹60,000 per tooth",
        "emi_eligible": True,
        "url_path": "/services/dental-implants",
        "pros": ["Preserves jawbone", "Lasts 15-20+ years", "Looks and feels like a natural tooth"],
        "cons": ["Requires minor surgery", "Healing period of several months", "Higher upfront cost"],
        "alternative_to": ["bridge", "denture_partial"],
        "precedes": [],
    },
    "full_mouth_implant": {
        "id": "full_mouth_implant",
        "name": "Full Mouth Dental Implants",
        "category": "implants",
        "short": "Replaces an entire arch (upper or lower) of teeth with a fixed implant-supported prosthesis.",
        "typical_duration": "Usually 1-2 surgical sittings followed by 3-6 months healing before final teeth",
        "recovery": "soft foods 2-4 weeks; full recovery 3-6 months; AI-guided precision reduces tissue trauma",
        "price_band": "₹3L – ₹8L per arch",
        "emi_eligible": True,
        "url_path": "/full-mouth-dental-implants",
        "pros": ["Permanent fix", "Restores chewing and speech", "Prevents bone loss"],
        "cons": ["Surgical procedure", "Higher cost", "Multi-month timeline"],
        "alternative_to": ["denture_full"],
        "precedes": [],
    },
    "bridge": {
        "id": "bridge",
        "name": "Dental Bridge",
        "category": "restorative",
        "short": "Replaces a missing tooth by anchoring a false tooth to the two healthy neighbouring teeth.",
        "typical_duration": "2-3 visits over 2-4 weeks",
        "recovery": "minor sensitivity for a few days",
        "price_band": "₹15,000 – ₹30,000",
        "emi_eligible": True,
        "url_path": "/services/bridges",
        "pros": ["Faster than implants", "No surgery", "Lower upfront cost"],
        "cons": ["Requires shaping healthy neighbouring teeth", "Doesn't preserve jawbone", "Lasts 7-10 years typically"],
        "alternative_to": ["single_implant", "denture_partial"],
        "precedes": [],
    },
    "denture_partial": {
        "id": "denture_partial",
        "name": "Partial Denture",
        "category": "restorative",
        "short": "A removable appliance that fills the space left by missing teeth.",
        "typical_duration": "2-4 visits over 3-6 weeks",
        "recovery": "adjustment period of 1-2 weeks",
        "price_band": "₹10,000 – ₹25,000",
        "emi_eligible": False,
        "url_path": "/services/complete-dentures",
        "pros": ["Most affordable option", "Non-surgical", "Removable for cleaning"],
        "cons": ["Less stable than fixed options", "Requires daily cleaning", "May feel bulky initially"],
        "alternative_to": ["bridge", "single_implant"],
        "precedes": [],
    },
    "denture_full": {
        "id": "denture_full",
        "name": "Full Denture",
        "category": "restorative",
        "short": "A complete removable set of upper and/or lower teeth.",
        "typical_duration": "4-6 visits over 4-8 weeks",
        "recovery": "adjustment period of 2-4 weeks",
        "price_band": "₹20,000 – ₹60,000 per arch",
        "emi_eligible": False,
        "url_path": "/services/complete-dentures",
        "pros": ["Non-surgical", "Lower cost than implants", "Restores appearance and basic function"],
        "cons": ["Less chewing efficiency than implants", "Can shift while eating/speaking", "Bone continues to recede over time"],
        "alternative_to": ["full_mouth_implant"],
        "precedes": [],
    },
    "clear_aligners": {
        "id": "clear_aligners",
        "name": "Clear Aligners",
        "category": "orthodontics",
        "short": "Custom transparent trays that gradually straighten teeth — nearly invisible and removable.",
        "typical_duration": "Mild cases: 6-12 months; moderate: 12-18 months",
        "recovery": "no recovery needed; mild pressure for 2-3 days after each tray change",
        "price_band": "₹70,000 – ₹2,50,000 (severity-dependent)",
        "emi_eligible": True,
        "url_path": "/services/aligners",
        "pros": ["Nearly invisible", "Removable for eating and cleaning", "Fewer dental visits than braces"],
        "cons": ["Requires 20-22 hr/day wear", "Less effective for severe cases", "Higher upfront cost than braces"],
        "alternative_to": ["metal_braces"],
        "precedes": [],
    },
    "metal_braces": {
        "id": "metal_braces",
        "name": "Metal Braces",
        "category": "orthodontics",
        "short": "Traditional fixed orthodontic appliance — brackets and wires that move teeth into alignment.",
        "typical_duration": "12-24 months typically",
        "recovery": "mild soreness for a few days after each adjustment",
        "price_band": "₹35,000 – ₹80,000",
        "emi_eligible": True,
        "url_path": "/services/braces",
        "pros": ["Effective for all severities", "Lower cost than aligners", "No discipline needed (always on)"],
        "cons": ["Visible", "Food restrictions (no sticky/hard foods)", "Harder to clean", "More dental visits"],
        "alternative_to": ["clear_aligners"],
        "precedes": [],
    },
    "teeth_whitening": {
        "id": "teeth_whitening",
        "name": "Teeth Whitening",
        "category": "cosmetic",
        "short": "Professional bleaching that lightens tooth shade by several levels — in-clinic or take-home.",
        "typical_duration": "1-2 in-clinic sessions of ~60 min, or 2 weeks at home",
        "recovery": "no recovery; mild sensitivity for 24-48 hours possible",
        "price_band": "₹5,000 – ₹15,000",
        "emi_eligible": False,
        "url_path": "/services/teeth-whitening",
        "pros": ["Fast results", "Non-invasive", "Affordable cosmetic upgrade"],
        "cons": ["Not permanent (1-3 years)", "May cause temporary sensitivity", "Not effective on crowns/veneers"],
        "alternative_to": ["veneers"],
        "precedes": [],
    },
    "veneers": {
        "id": "veneers",
        "name": "Dental Veneers",
        "category": "cosmetic",
        "short": "Thin porcelain or composite shells bonded to the front of teeth to improve shape, color, and alignment.",
        "typical_duration": "2-3 visits over 2-4 weeks",
        "recovery": "minimal; mild sensitivity for a few days",
        "price_band": "₹8,000 – ₹25,000 per tooth",
        "emi_eligible": True,
        "url_path": "/services/veneers",
        "pros": ["Long-lasting (10-20 yrs)", "Stain-resistant", "Fixes multiple cosmetic issues at once"],
        "cons": ["Requires removing a thin layer of enamel (irreversible)", "Higher cost", "Can chip if abused"],
        "alternative_to": ["teeth_whitening", "dental_bonding"],
        "precedes": [],
    },
    "dental_bonding": {
        "id": "dental_bonding",
        "name": "Dental Bonding",
        "category": "cosmetic",
        "short": "Tooth-coloured resin applied to close small gaps, reshape teeth, or repair minor chips.",
        "typical_duration": "Single 30-60 min visit",
        "recovery": "no recovery needed",
        "price_band": "₹2,500 – ₹6,000 per tooth",
        "emi_eligible": False,
        "url_path": "/services/dental-bonding",
        "pros": ["Single visit", "No enamel removal", "Affordable"],
        "cons": ["Less durable than veneers (5-7 yrs)", "Can stain", "Not suitable for large gaps"],
        "alternative_to": ["veneers"],
        "precedes": [],
    },
    "cleaning": {
        "id": "cleaning",
        "name": "Dental Cleaning & Scaling",
        "category": "general",
        "short": "Professional removal of plaque, tartar, and surface stains; recommended every 6 months.",
        "typical_duration": "Single 30-60 min visit",
        "recovery": "none",
        "price_band": "₹800 – ₹2,500",
        "emi_eligible": False,
        "url_path": "/services/dental-cleaning-and-scaling",
        "pros": ["Essential preventive care", "Brightens teeth", "Detects issues early"],
        "cons": ["Mild sensitivity for a day"],
        "alternative_to": [],
        "precedes": ["teeth_whitening", "veneers", "dental_bonding"],
    },
    "root_canal": {
        "id": "root_canal",
        "name": "Root Canal Treatment",
        "category": "restorative",
        "short": "Removes infected pulp from inside a tooth and seals it — saves a tooth that would otherwise be extracted.",
        "typical_duration": "1-2 visits of ~60-90 min each",
        "recovery": "mild discomfort for 2-3 days",
        "price_band": "₹4,000 – ₹10,000",
        "emi_eligible": False,
        "url_path": "/services/root-canal",
        "pros": ["Saves the natural tooth", "Eliminates pain", "Cheaper than extraction + implant"],
        "cons": ["Requires crown afterwards", "Possible repeat if infection returns"],
        "alternative_to": [],
        "precedes": [],
    },
    "consultation": {
        "id": "consultation",
        "name": "Free Consultation",
        "category": "general",
        "short": "An exam with a Dezy dentist to diagnose your issue and walk you through options.",
        "typical_duration": "30-45 min",
        "recovery": "none",
        "price_band": "Free",
        "emi_eligible": False,
        "url_path": "/free-smile-consultation",
        "pros": ["Free", "Personalised plan", "Includes X-ray review if needed"],
        "cons": [],
        "alternative_to": [],
        "precedes": [],
    },
}


# ============================================================================
# Slots — clinical context the interviewer collects
# ============================================================================

class Slot(TypedDict):
    id: str
    question: str
    quick_replies: list[str]   # ranked first to last; first is most-likely
    accepts_freeform: bool


SLOTS: dict[str, Slot] = {
    "permanence_preference": {
        "id": "permanence_preference",
        "question": "Do you want a permanent fix, or something removable?",
        "quick_replies": ["Permanent", "Removable", "Open to both"],
        "accepts_freeform": False,
    },
    "surgery_comfort": {
        "id": "surgery_comfort",
        "question": "Are you comfortable with a minor surgical procedure?",
        "quick_replies": ["Yes", "I'd prefer to avoid it", "I'm anxious — want to know more first"],
        "accepts_freeform": True,
    },
    "severity": {
        "id": "severity",
        "question": "How would you describe the severity?",
        "quick_replies": ["Mild", "Moderate", "Severe"],
        "accepts_freeform": False,
    },
    "timeline_months": {
        "id": "timeline_months",
        "question": "Is there a deadline you want to be done by? (e.g. an event, wedding)",
        "quick_replies": ["No deadline", "Within 6 months", "Within 12 months", "More than a year is fine"],
        "accepts_freeform": True,
    },
    "visibility_preference": {
        "id": "visibility_preference",
        "question": "How important is it that the treatment be invisible while in use?",
        "quick_replies": ["Very important", "Somewhat", "Doesn't matter"],
        "accepts_freeform": False,
    },
    "budget_band": {
        "id": "budget_band",
        "question": "Do you have a rough budget in mind? EMI options are usually available.",
        "quick_replies": ["Under ₹50k", "₹50k – ₹1L", "₹1L – ₹3L", "₹3L+", "I'd like to use EMI"],
        "accepts_freeform": True,
    },
    "sensitivity_known": {
        "id": "sensitivity_known",
        "question": "Do you have sensitive teeth currently?",
        "quick_replies": ["No", "Yes, mildly", "Yes, significantly"],
        "accepts_freeform": False,
    },
    "pain_severity": {
        "id": "pain_severity",
        "question": "How severe is the pain?",
        "quick_replies": ["Mild", "Moderate", "Severe — it's hard to function"],
        "accepts_freeform": True,
    },
    "pain_duration": {
        "id": "pain_duration",
        "question": "How long have you had the pain?",
        "quick_replies": ["A few hours", "A few days", "More than a week"],
        "accepts_freeform": True,
    },
}


# ============================================================================
# Clinical escalation triggers — keywords that route a message to fallback
# (human handoff) rather than producing a treatment recommendation
# ============================================================================

ESCALATION_TRIGGERS: list[dict[str, str]] = [
    {
        "category": "acute_symptom",
        "keywords": ["bleeding won't stop", "uncontrolled bleeding", "trouble breathing", "swollen face severely", "fever with tooth"],
        "reason": "Possible dental emergency — please contact a Dezy clinic immediately or visit a hospital.",
    },
    {
        "category": "pregnancy_xray",
        "keywords": ["pregnant", "pregnancy", "expecting a baby"],
        "reason": "Some procedures (especially x-rays) need special precautions during pregnancy. A clinician should review your case directly.",
    },
    {
        "category": "cardiac",
        "keywords": ["heart attack", "heart condition", "blood thinner", "pacemaker"],
        "reason": "Cardiac history can affect treatment planning and anaesthesia choices. A clinician should review your case before any procedure.",
    },
    {
        "category": "bleeding_disorder",
        "keywords": ["haemophilia", "hemophilia", "bleeding disorder", "von willebrand"],
        "reason": "Bleeding disorders require special protocols. Please consult a clinician directly.",
    },
    {
        "category": "minor",
        "keywords": ["my child", "my daughter aged 5", "my son aged", "for a 4 year old", "for a toddler"],
        "reason": "For paediatric patients, please book a consultation directly so a paediatric dentist can assess.",
    },
]


# ============================================================================
# Default CTAs and persona — used by the safety node
# ============================================================================

PERSONA_SYSTEM_PROMPT = (
    "You are Dezy's AI dental advisor. Your tone is calm, reassuring, and "
    "non-pushy. You speak in plain language (no jargon unless you explain it). "
    "You acknowledge a patient's anxiety when present. You never diagnose, "
    "prescribe medication, or guarantee outcomes — your job is to inform and "
    "guide the next step. You always make it clear that final decisions are "
    "made with a Dezy clinician."
)

DEFAULT_DISCLAIMER = (
    "This guidance is informational only and is not a substitute for a "
    "clinical exam by a qualified dentist."
)

BOOK_CONSULT_CTA = {
    "label": "Book a Free Consultation",
    "url": "https://www.dezy.com/new-appointment-flow",
    "kind": "primary",
}

COST_CALCULATOR_CTA = {
    "label": "Open Cost Calculator",
    "url": "https://www.dezy.com/treatment-cost-calculator",
    "kind": "secondary",
}

IMPLANT_COST_CALCULATOR_CTA = {
    "label": "Open Cost Calculator",
    "url": "https://www.dezy.com/dental-implants-cost-calculator",
    "kind": "secondary",
}

# Multi-channel contact options shown when the agent can't confidently answer
# and wants to hand the user to a real human. Order matters — primary
# Book CTA first, then easiest-to-fastest alternative channels.
CONTACT_CHANNELS_CTAS = [
    BOOK_CONSULT_CTA,
    {
        "label": "Chat on WhatsApp",
        "url": "https://api.whatsapp.com/send?phone=+917618792440&text=Hello%20Dezy",
        "kind": "secondary",
    },
    {
        "label": "Call (New Patients)",
        "url": "tel:+917618792440",
        "kind": "secondary",
    },
    {
        "label": "Call (Ongoing Patients)",
        "url": "tel:+918047362299",
        "kind": "secondary",
    },
    {
        "label": "Browse FAQs",
        "url": "https://www.dezy.com/faqs",
        "kind": "secondary",
    },
]


def find_concern(text: str) -> Concern | None:
    """Naive keyword match — for the router's coarse pre-classification."""
    lower = text.lower()
    for concern in CONCERNS.values():
        if concern["id"].replace("_", " ") in lower:
            return concern
        for synonym in concern["synonyms"]:
            if synonym.lower() in lower:
                return concern
    return None


def find_escalation(text: str) -> dict[str, str] | None:
    """Return the first matching escalation trigger, if any."""
    lower = text.lower()
    for trigger in ESCALATION_TRIGGERS:
        for keyword in trigger["keywords"]:
            if keyword in lower:
                return trigger
    return None


def treatments_for_concern(concern_id: str) -> list[Treatment]:
    concern = CONCERNS.get(concern_id)
    if not concern:
        return []
    return [TREATMENTS[t] for t in concern["treats"] if t in TREATMENTS]
