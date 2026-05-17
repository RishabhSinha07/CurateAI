"""Dezy brand-supplied content as typed Python data.

Source: Dezy Brand Overview Document v1 (provided by Dezy team).
When Dezy hands us a new revision of the doc, update this file and
re-run `scripts.dezy_brand.build_snapshot` + `scripts.ingest_dezy`.

Sections map to ingestion targets:
  - PER_TREATMENT_DEZY_ADVANTAGE  → merged into services.attributes.dezy_advantage
  - BRAND_CONTENT_CHUNKS          → content_chunks (RAG corpus, trust=brand_doc)
  - NAMED_DOCTOR_CASE_COUNTS      → doctors.attributes.cases_done (overrides scrape)
"""

from __future__ import annotations

from typing import TypedDict


# ============================================================================
# Per-treatment "Dezy Advantage" — merged into existing services.attributes
# Keys must match dezy.com service slugs (the scraper uses these exact ids).
# ============================================================================

PER_TREATMENT_DEZY_ADVANTAGE: dict[str, str] = {
    "dental-implants":             "2,000–15,000+ implants by specialists; premium materials.",
    "full-mouth-dental-implants":  "Done by senior implantologists (10,000+ cases each).",
    "aligners":                    "Free in-clinic scan, AI smile preview, home delivery.",
    "braces":                      "MDS orthodontists; metal and aesthetic options available.",
    "root-canal":                  "Painless; often completed in a single sitting.",
    "veneers":                     "Digital smile preview before treatment; precision-crafted shells.",
    "teeth-whitening":             "Visible results in one in-clinic session.",
    "bridges":                     "Digitally-fitted; accurate seating without trial-and-error.",
    "dental-bonding":              "Quick, single-visit cosmetic correction.",
    "tooth-extraction":            "Pain-controlled; surgical extraction available when needed.",
    "dental-cleaning-and-scaling": "Preventive care every 6 months; recommended for all patients.",
    "complete-dentures":           "Custom-fit, natural-looking dentures.",
    "dental-jewellery":            "Reversible, non-invasive cosmetic enhancement.",
}


# ============================================================================
# Named-doctor case-count overrides — merged into doctors.attributes.cases_done
# Keys are the doctor slugs (verified against the existing scrape).
# Brand-supplied numbers take precedence over scrape-extracted ones because the
# scrape pulls the "cases done" badge from the doctor's profile page, which
# Dezy says is occasionally stale.
# ============================================================================

NAMED_DOCTOR_CASE_COUNTS: dict[str, dict] = {
    "dr-faiz":          {"cases_done": 15000, "tier": "senior_implantologist"},
    "dr-vinay-paVan":   {"cases_done": 10000, "tier": "senior_implantologist"},
    "dr-jatin-kakrani": {"cases_done": 10000, "tier": "senior_implantologist"},
}


# ============================================================================
# Brand content chunks — ingested as content_chunks rows.
# These are NOT scraped from any URL. We give them synthetic source_urls so
# their provenance is clear in the DB.
#
# `chunk_text` is what the RAG retrieval sees. Keep it self-contained and
# specific — the LLM grounds answers in these verbatim.
# ============================================================================

class BrandChunk(TypedDict):
    topic: str          # short identifier — becomes the URL slug
    title: str          # human title
    section: str        # for metadata.section
    text: str           # the chunk content


BRAND_CONTENT_CHUNKS: list[BrandChunk] = [
    {
        "topic": "core_promises",
        "title": "Dezy's three core promises",
        "section": "promises",
        "text": (
            "Every treatment at Dezy is built on three promises: Low Price (direct sourcing, "
            "no middlemen), High Quality (MDS specialists and strict clinical protocols), and "
            "100% Outcome Assurance (full refund if you are not satisfied with your treatment). "
            "These are non-negotiable across every clinic and every service."
        ),
    },
    {
        "topic": "outcome_assurance_refund",
        "title": "100% Outcome Assurance — refund policy",
        "section": "promises",
        "text": (
            "Dezy offers a 100% Outcome Assurance: if you are not satisfied with the result of "
            "your treatment, Dezy will refund you in full. This applies across all treatments."
        ),
    },
    {
        "topic": "why_dezy",
        "title": "Why patients choose Dezy",
        "section": "why_dezy",
        "text": (
            "Patients choose Dezy because we are completely honest about pricing (no hidden costs), "
            "digital-first (tech-driven, consistent outcomes), low-priced (direct sourcing, no "
            "middlemen), high-quality (MDS specialists, strict protocols), backed by 100% Outcome "
            "Assurance (full refund if not satisfied), and accessible (free home scan, EMI options, "
            "7-day clinics)."
        ),
    },
    {
        "topic": "transparent_pricing",
        "title": "Transparent, upfront pricing",
        "section": "why_dezy",
        "text": (
            "Dezy publishes upfront pricing for every treatment and uses a pricing engine to "
            "generate clear cost estimates before you begin. There are no hidden charges or "
            "surprise add-ons. EMI options are available across most treatments to make care affordable."
        ),
    },
    {
        "topic": "tech_overview",
        "title": "Dezy's digital-first technology stack",
        "section": "technology",
        "text": (
            "Dezy is fully digital across the patient journey. Diagnostic and smile mapping use "
            "Digital Scanning and Intra-Oral Scanners for fast, comfortable, accurate impressions. "
            "Digital X-Ray provides imaging with low radiation. Treatment Planning Software "
            "personalises every plan, and a Pricing Engine produces accurate cost estimates upfront. "
            "AI Smile Simulation lets patients preview their outcome before treatment, and 3D "
            "Printing produces aligners and crowns with precise fit. Treatment Monitoring tracks "
            "progress for quality control."
        ),
    },
    {
        "topic": "tech_ai_smile_simulation",
        "title": "AI Smile Simulation — preview your result",
        "section": "technology",
        "text": (
            "Before you commit to a cosmetic or orthodontic treatment, Dezy's AI Smile Simulation "
            "shows you what your smile will look like after treatment. This works for aligners, "
            "veneers, and full smile makeovers. The preview is generated from a digital scan and "
            "shared during your free consultation."
        ),
    },
    {
        "topic": "tech_3d_printing_scanning",
        "title": "Digital scanning and 3D printing",
        "section": "technology",
        "text": (
            "Dezy uses intra-oral scanners (instead of traditional putty impressions) to capture "
            "your teeth digitally. Aligners and crowns are then produced via 3D printing, giving "
            "a faster turnaround and more precise fit than conventional lab work."
        ),
    },
    {
        "topic": "doctor_network_standards",
        "title": "Network standards for Dezy doctors",
        "section": "doctors",
        "text": (
            "Every Dezy doctor is an MDS specialist. Across the network: minimum 7+ years of "
            "experience; implant doctors each have 2,000-3,000+ cases under their belt; "
            "continuous training on the latest technology; strong internal quality audits. "
            "Specialties covered: Implantology, Orthodontics (Aligners and Braces), Endodontics "
            "(Root Canal), Prosthodontics (Crowns, Bridges, Dentures), Cosmetic Dentistry, "
            "and General Dentistry and Periodontics."
        ),
    },
    {
        "topic": "senior_implantologists",
        "title": "Dezy's senior implantologists",
        "section": "doctors",
        "text": (
            "Dezy's senior implantologists each have over 10,000 implant cases: Dr. Faiz "
            "(15,000+ implants), Dr. Vinay (10,000+ implants), and Dr. Jatin (10,000+ "
            "implants). For complex or full-mouth cases, these doctors are typically involved "
            "either directly or as part of the treatment-planning team."
        ),
    },
    {
        "topic": "awards_recognition",
        "title": "Awards and recognition",
        "section": "awards",
        "text": (
            "Dezy has been recognised as the Best Dental Care Clinic in South India by the "
            "Economic Times, listed among the Top 10 Startups in India in Digital Dentistry by "
            "the World Economic Forum, and is the 2024 Voice of Healthcare Award winner for "
            "Healthcare Innovation."
        ),
    },
    {
        "topic": "company_overview",
        "title": "About Dezy",
        "section": "company",
        "text": (
            "Dezy is one of India's fastest-growing digital-first dental chains, founded in 2019 "
            "by IIT and IIM alumni and backed by leading institutional investors. Dezy operates "
            "across Bangalore (multiple locations including Rajajinagar, HSR Layout, Marathahalli, "
            "Koramangala, Hebbal, JP Nagar, Basavanagudi, Electronic City, Bannerghatta Road, "
            "Indiranagar, and more), plus Hyderabad (LB Nagar, Somajiguda) and Pune (Balewadi)."
        ),
    },
    {
        "topic": "accessibility_home_scan_emi",
        "title": "Accessible care: free home scan, EMI, 7-day clinics",
        "section": "why_dezy",
        "text": (
            "Dezy makes care easy to access: free in-clinic and (for aligners) at-home digital "
            "scans, 0% EMI options on most treatments, and clinics open 7 days a week. The first "
            "consultation is always free."
        ),
    },
]
