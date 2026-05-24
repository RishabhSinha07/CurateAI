"""Emit a brand-content snapshot in the same JSON shape as the scraper.

`scripts.ingest_dezy` loads this with the same code path — only the
--snapshot arg changes.

Output sections:
  services       — empty (we only PATCH existing services via attributes;
                   ingest_dezy.upsert_service will merge attributes into rows
                   that already exist, no-op for rows that don't)
  doctors        — empty similarly (only case-count attribute overrides)
  clinics        — empty
  content_chunks — brand RAG corpus

We emit `services` and `doctors` entries only when we need to enhance an
existing row's attributes (per-treatment dezy_advantage, named-doctor case
counts). The ingester is upsert-by-slug so these merge cleanly with rows
the scraper already wrote.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from scripts.dezy_brand.content import (
    BRAND_CONTENT_CHUNKS,
    NAMED_DOCTOR_CASE_COUNTS,
    PER_TREATMENT_DEZY_ADVANTAGE,
)

logger = logging.getLogger("dezy_brand")

BRAND_SOURCE = "internal://dezy/brand_doc/v1"


def build_service_patches() -> list[dict]:
    """For each treatment that has a brand `dezy_advantage`, emit a minimal
    service row keyed by slug. The ingester's upsert merges the attributes
    dict onto the existing scraped row (or no-ops if not present)."""
    rows: list[dict] = []
    for slug, advantage in PER_TREATMENT_DEZY_ADVANTAGE.items():
        rows.append({
            "slug": slug,
            # Stable shape the ingester expects (mostly ignored for existing rows)
            "name": slug.replace("-", " ").title(),
            "category": "general",
            "description": None,
            "currency": "INR",
            "price_min": None,
            "price_max": None,
            "url": f"https://www.dezy.com/services/{slug}",
            # The interesting payload:
            "attributes": {
                "dezy_advantage": advantage,
                "brand_doc_version": "v1",
            },
        })
    return rows


def build_doctor_patches() -> list[dict]:
    """One row per named senior implantologist. Slugs already verified to
    exist in the scrape so the upsert hits and merges attributes."""
    rows: list[dict] = []
    for slug, info in NAMED_DOCTOR_CASE_COUNTS.items():
        rows.append({
            "slug": slug,
            "full_name": slug.replace("-", " ").title().replace("Dr ", "Dr. "),
            "city": None,
            "gender": None,
            "specializations": [],
            "credentials": [],
            "languages": [],
            "experience_years": None,
            "bio": None,
            "url": None,
            "rating": None,
            # Brand-supplied case count + tier override
            "attributes": {
                "cases_done": info["cases_done"],
                "tier": info["tier"],
                "brand_doc_version": "v1",
            },
        })
    return rows


def build_content_chunks() -> list[dict]:
    """Each BrandChunk becomes a content_chunks row with synthetic source_url."""
    chunks: list[dict] = []
    for i, c in enumerate(BRAND_CONTENT_CHUNKS):
        chunks.append({
            "source_url": f"{BRAND_SOURCE}/{c['topic']}",
            "source_type": "brand",
            "title": c["title"],
            "chunk_index": 0,                   # one chunk per brand topic
            "chunk_text": c["text"],
            "metadata": {
                "section": c["section"],
                "topic": c["topic"],
                "trust_tier": "brand_doc",
                "brand_doc_version": "v1",
            },
        })
    return chunks


def build(out_path: Path) -> None:
    snapshot = {
        "services":       build_service_patches(),
        "doctors":        build_doctor_patches(),
        "clinics":        [],
        "content_chunks": build_content_chunks(),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    logger.info(
        "Wrote brand snapshot: %s (service-patches=%d, doctor-patches=%d, content_chunks=%d)",
        out_path,
        len(snapshot["services"]),
        len(snapshot["doctors"]),
        len(snapshot["content_chunks"]),
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    p = argparse.ArgumentParser()
    p.add_argument(
        "--out",
        default="/app/scripts/dezy_brand/output/brand_snapshot.json",
    )
    args = p.parse_args()
    build(Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
