"""Page parsers for dezy.com.

All parsers operate on raw HTML strings. We extract:

  - JSON-LD blocks (services pages have rich Schema.org markup)
  - Doctor profile fields via tagged-text regex
  - Clinic detail fields via tagged-text regex
  - FAQ Q&As from Schema.org FAQPage blocks
  - Procedural content from MedicalProcedure blocks

We avoid a full HTML parser dependency by stripping tags and using
targeted regex against the visible text. The site is server-rendered
Next.js so the visible content is in the HTML.
"""

from __future__ import annotations

import html as html_mod
import json
import re
from typing import Any, Iterable

JSON_LD_RE = re.compile(
    r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL,
)
SCRIPT_RE = re.compile(r"<script.*?</script>", re.DOTALL | re.IGNORECASE)
STYLE_RE = re.compile(r"<style.*?</style>", re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def visible_text(html: str) -> str:
    """Return the visible body text of an HTML page, normalized."""
    stripped = SCRIPT_RE.sub(" ", html)
    stripped = STYLE_RE.sub(" ", stripped)
    stripped = TAG_RE.sub(" ", stripped)
    stripped = html_mod.unescape(stripped)
    return WS_RE.sub(" ", stripped).strip()


def parse_json_ld(html: str) -> list[Any]:
    """Yield parsed JSON-LD objects from a page (skipping malformed blocks)."""
    blocks: list[Any] = []
    for raw in JSON_LD_RE.findall(html):
        try:
            blocks.append(json.loads(raw.strip()))
        except json.JSONDecodeError:
            continue
    return blocks


def find_jsonld_by_type(html: str, type_name: str) -> dict | None:
    """First JSON-LD block whose @type matches type_name."""
    for block in parse_json_ld(html):
        if isinstance(block, dict) and block.get("@type") == type_name:
            return block
    return None


def find_jsonld_all_of_type(html: str, type_name: str) -> list[dict]:
    return [
        b for b in parse_json_ld(html)
        if isinstance(b, dict) and b.get("@type") == type_name
    ]


# ---------------------------------------------------------------------------
# Service page parser
# ---------------------------------------------------------------------------

def slug_to_category(slug: str) -> str:
    """Map a service slug to one of our catalog categories."""
    s = slug.lower()
    if any(k in s for k in ("implant", "denture", "bridge", "root-canal", "extraction")):
        return "implants" if "implant" in s else "restorative"
    if any(k in s for k in ("aligner", "braces")):
        return "orthodontics"
    if any(k in s for k in ("veneer", "whitening", "bonding", "jewellery", "jewelry")):
        return "cosmetic"
    return "general"


def parse_service_page(url: str, slug: str, html: str) -> dict | None:
    """Extract one service record from a /services/<slug> page."""
    service_jsonld = find_jsonld_by_type(html, "Service")
    procedure = find_jsonld_by_type(html, "MedicalProcedure")
    if service_jsonld is None and procedure is None:
        return None

    name = (service_jsonld or {}).get("name") or (procedure or {}).get("name")
    description = (service_jsonld or {}).get("description") or (procedure or {}).get("description")

    price_min = None
    price_max = None
    offers = (service_jsonld or {}).get("offers") or {}
    if isinstance(offers, dict):
        spec = offers.get("priceSpecification") or {}
        if isinstance(spec, dict):
            try:
                price_min = float(spec.get("minPrice")) if spec.get("minPrice") else None
                price_max = float(spec.get("maxPrice")) if spec.get("maxPrice") else None
            except (ValueError, TypeError):
                pass

    return {
        "slug": slug,
        "url": url,
        "name": name or slug.replace("-", " ").title(),
        "category": slug_to_category(slug),
        "description": description,
        "price_min": price_min,
        "price_max": price_max,
        "currency": "INR",
    }


def parse_faq_chunks(url: str, page_title: str | None, html: str) -> list[dict]:
    """Each Q&A in the page's FAQPage block becomes a content chunk."""
    chunks: list[dict] = []
    faq = find_jsonld_by_type(html, "FAQPage")
    if faq is None:
        return chunks
    entities = faq.get("mainEntity") or []
    for idx, q in enumerate(entities):
        if not isinstance(q, dict):
            continue
        question = (q.get("name") or "").strip()
        answer_block = q.get("acceptedAnswer") or {}
        answer = (answer_block.get("text") or "").strip()
        if not question or not answer:
            continue
        chunks.append({
            "source_url": url,
            "source_type": "faq",
            "title": question,
            "chunk_index": idx,
            "chunk_text": f"Q: {question}\nA: {answer}",
            "metadata": {"page_title": page_title, "section": "faq"},
        })
    return chunks


def parse_procedure_chunks(url: str, page_title: str | None, html: str) -> list[dict]:
    """MedicalProcedure → up to 3 chunks (preparation, howPerformed, followup)."""
    proc = find_jsonld_by_type(html, "MedicalProcedure")
    if proc is None:
        return []
    name = proc.get("name") or page_title or url
    chunks: list[dict] = []
    for section in ("preparation", "howPerformed", "followup"):
        text = (proc.get(section) or "").strip()
        if not text:
            continue
        chunks.append({
            "source_url": url,
            "source_type": "page",
            "title": f"{name} — {section.replace('Performed', '').title().strip() or 'How Performed'}",
            "chunk_index": 100 + len(chunks),  # offset so FAQ chunks keep 0..N
            "chunk_text": text,
            "metadata": {"page_title": page_title, "section": section},
        })
    return chunks


# ---------------------------------------------------------------------------
# Doctor page parser
# ---------------------------------------------------------------------------

RE_RATING = re.compile(r"RATING\s+([\d.]+)\s*/\s*5", re.IGNORECASE)
RE_CASES = re.compile(r"CASES DONE\s+([\d,]+)", re.IGNORECASE)
RE_EXP = re.compile(r"EXPERIENCE\s+([\d.]+)\s*yrs?", re.IGNORECASE)
RE_LANGS = re.compile(r"Languages known:\s*([A-Za-z, ]+?)\.", re.IGNORECASE)

# Specializations live between "Specializations" and the next heading
# ("Smiles and Satisfaction" is the next visible header on every doctor page).
RE_SPECS = re.compile(
    r"Specializations\s+(.+?)\s+(?:Smiles and Satisfaction|Book free consultation)",
    re.IGNORECASE | re.DOTALL,
)

# City appears in the breadcrumb/header just before "Book free consultation".
RE_CITY = re.compile(
    r"View all dentists\s+(\w+)\s+Book free consultation",
    re.IGNORECASE,
)

# Bio is the long sentence(s) between EXPERIENCE ... yrs and "Languages known:"
RE_BIO = re.compile(
    r"EXPERIENCE\s+[\d.]+\s*yrs?\s+(.+?)\s+Languages known:",
    re.IGNORECASE | re.DOTALL,
)

# Credentials appear between the doctor's first name and the RATING label,
# e.g. "Dr Aamir MDS RATING 4.8 /5" or "Dr Foo BDS, MDS RATING ...".
# We capture the uppercase tokens between the first-name word and RATING.
RE_CREDENTIALS = re.compile(
    r"\bDr\s+[A-Z][a-z]+\s+([A-Z][A-Z,./& ]*?)\s+RATING",
    re.IGNORECASE,
)

KNOWN_SPECIALIZATIONS = {
    "orthodontics": ["orthodontics", "ortho", "aligner", "braces", "dentofacial", "entofacial"],
    "implants": ["implant", "implantology", "implantologist"],
    "cosmetic": ["cosmetic", "smile design", "veneer"],
    "endodontics": ["endodontics", "endo", "root canal"],
    "prosthodontics": ["prosthodontics", "prostho"],
    "periodontics": ["periodontics", "perio", "gum"],
    "paediatric": ["paediatric", "pediatric"],
    "general": ["general", "family", "scaling", "cleaning"],
}


def infer_specializations(spec_text: str) -> list[str]:
    """Map free-text specializations to our canonical lower_snake set."""
    text = spec_text.lower()
    matches: list[str] = []
    for canon, syns in KNOWN_SPECIALIZATIONS.items():
        if any(s in text for s in syns):
            matches.append(canon)
    return matches or ["general"]


PRONOUN_SHE = re.compile(r"\b(she|her)\b", re.IGNORECASE)
PRONOUN_HE = re.compile(r"\b(he|him|his)\b", re.IGNORECASE)


def infer_gender(bio: str | None) -> str | None:
    if not bio:
        return None
    she = len(PRONOUN_SHE.findall(bio))
    he = len(PRONOUN_HE.findall(bio))
    if she > he:
        return "F"
    if he > she:
        return "M"
    return None


def parse_doctor_page(url: str, slug: str, html: str) -> dict | None:
    text = visible_text(html)

    # The page title is "Dr X, City - Dezy Dental Treatments"
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else ""
    name_match = re.match(r"^(Dr[.\s][^,]+?),\s*([^-]+?)\s*-\s*Dezy", title)
    if name_match:
        full_name = name_match.group(1).strip()
        city = name_match.group(2).strip().title()
    else:
        full_name = slug.replace("-", " ").title()
        city = None

    bio_match = RE_BIO.search(text)
    bio = bio_match.group(1).strip() if bio_match else None

    rating = RE_RATING.search(text)
    cases = RE_CASES.search(text)
    exp = RE_EXP.search(text)
    langs = RE_LANGS.search(text)
    specs = RE_SPECS.search(text)
    creds = RE_CREDENTIALS.search(text)
    city_in_text = RE_CITY.search(text)
    if not city and city_in_text:
        city = city_in_text.group(1).strip().title()

    languages_list: list[str] = []
    if langs:
        languages_list = [l.strip() for l in langs.group(1).split(",") if l.strip()]
    specializations_list = infer_specializations(specs.group(1)) if specs else []
    credentials_list: list[str] = []
    if creds:
        credentials_list = [c.strip() for c in re.split(r"[,/&]", creds.group(1)) if c.strip()]

    return {
        "slug": slug,
        "url": url,
        "full_name": full_name,
        "city": city,
        "gender": infer_gender(bio),
        "specializations": specializations_list,
        "credentials": credentials_list,
        "languages": languages_list,
        "experience_years": int(float(exp.group(1))) if exp else None,
        "rating": float(rating.group(1)) if rating else None,
        "cases_done": int(cases.group(1).replace(",", "")) if cases else None,
        "bio": bio,
    }


# ---------------------------------------------------------------------------
# Clinic page parser
# ---------------------------------------------------------------------------

def parse_clinic_page(url: str, city: str, slug: str, html: str) -> dict | None:
    """Extract one clinic record from a /clinics/<city>/<slug> page."""
    # Title format: "Best Dental Clinic in <Locality> - <City> | Dezy"
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else ""
    # Strip "| Dezy" or any Dezy-suffix and the "Best Dental Clinic in" prefix.
    name = title
    name = re.sub(r"^Best Dental Clinic in\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*[|\-]\s*Dezy.*$", "", name, flags=re.IGNORECASE).strip()
    # If the locality is followed by " - <City>", keep just the locality.
    name = re.sub(rf"\s*-\s*{re.escape(city)}\s*$", "", name, flags=re.IGNORECASE).strip()
    if not name:
        tail = slug.split("-")
        keep = [w for w in tail if w not in {"best", "dental", "clinic", city.lower()}]
        name = " ".join(keep).title() or slug

    # Address: best-effort regex on visible text for postal code or street markers
    text = visible_text(html)
    addr_match = re.search(
        r"(Address|Located at)[:\s]+([A-Z][^.]{20,200}?)(?:\s+Working hours|\s+Phone|\s+Get directions|\s+\d{6})",
        text,
        re.IGNORECASE,
    )
    address = addr_match.group(2).strip() if addr_match else None
    postal_match = re.search(r"\b(\d{6})\b", text)
    postal = postal_match.group(1) if postal_match else None

    return {
        "slug": slug,
        "url": url,
        "name": name,
        "city": city.title(),
        "address": address,
        "postal_code": postal,
    }
