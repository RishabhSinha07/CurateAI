"""Orchestrator: read sitemap → fetch each page → parse → write JSON snapshot.

Usage:
    docker compose exec app python -m scripts.scrape_dezy.main \
        --out /app/scripts/scrape_dezy/output/dezy_scrape.json

The snapshot has shape:
    {
      "services":      [{slug, url, name, category, description, price_min, price_max, currency}, ...],
      "doctors":       [{slug, url, full_name, city, gender, specializations,
                         credentials, languages, experience_years, rating,
                         cases_done, bio}, ...],
      "clinics":       [{slug, url, name, city, address, postal_code}, ...],
      "content_chunks":[{source_url, source_type, title, chunk_index,
                         chunk_text, metadata}, ...]
    }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

from scripts.scrape_dezy.fetcher import PoliteFetcher
from scripts.scrape_dezy.parsers import (
    parse_clinic_page,
    parse_content_page,
    parse_doctor_page,
    parse_faq_chunks,
    parse_procedure_chunks,
    parse_service_page,
)

SITEMAP_URL = "https://www.dezy.com/sitemap.xml"

logger = logging.getLogger("scrape_dezy")


# Top-level pages we explicitly skip (legal boilerplate + blog SEO).
SKIP_TOP_LEVEL = {"privacy-policy", "terms"}

# Catalog index pages — content lives in the per-item pages we already walk.
SKIP_INDEX = {"services", "meet-your-dentists"}


def _classify(url: str) -> tuple[str, str, str | None]:
    """Return (kind, slug, city_or_none) for a sitemap URL we care about."""
    path = urlsplit(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    if not parts:
        return ("skip", "", None)  # home page

    # /services/<slug>
    if len(parts) >= 2 and parts[0] == "services":
        return ("service", parts[1], None)

    # /meet-your-dentists/<slug>
    if len(parts) >= 2 and parts[0] == "meet-your-dentists":
        return ("doctor", parts[1], None)

    # /clinics/<city>/<leaf-slug> — individual clinic detail page
    if len(parts) >= 3 and parts[0] == "clinics":
        return ("clinic", parts[2], parts[1])

    # /clinics/<city> — city aggregator page (mostly FAQs at the bottom worth grabbing)
    if len(parts) == 2 and parts[0] == "clinics":
        return ("content", f"clinics-{parts[1]}", None)

    # Skip the blog tree entirely (we have FAQ + service content; blogs are SEO noise)
    if parts[0] == "blogs":
        return ("skip", "", None)

    # Top-level content pages (/why-dezy-is-different, /how-it-works-implants,
    # /cost-of-dental-implants, /faqs, /crowded-teeth, etc.)
    if len(parts) == 1:
        slug = parts[0]
        if slug in SKIP_TOP_LEVEL or slug in SKIP_INDEX:
            return ("skip", "", None)
        return ("content", slug, None)

    return ("skip", "", None)


def _load_sitemap_urls(sitemap_xml: str) -> list[str]:
    root = ET.fromstring(sitemap_xml)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [el.text.strip() for el in root.findall("sm:url/sm:loc", ns) if el.text]


def _title(html: str) -> str | None:
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    return m.group(1).strip() if m else None


async def scrape(out_path: Path, *, limit_per_kind: int | None = None) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    services: list[dict] = []
    doctors: list[dict] = []
    clinics: list[dict] = []
    content_chunks: list[dict] = []

    async with PoliteFetcher() as fetcher:
        # 1) Sitemap
        sitemap = await fetcher.get(SITEMAP_URL)
        urls = _load_sitemap_urls(sitemap)
        logger.info("Sitemap: %d urls", len(urls))

        # Group URLs by kind for predictable progress and easy limiting.
        by_kind: dict[str, list[tuple[str, str, str | None]]] = {
            "service": [], "doctor": [], "clinic": [], "content": [],
        }
        for url in urls:
            kind, slug, city = _classify(url)
            if kind in by_kind:
                by_kind[kind].append((url, slug, city))

        if limit_per_kind is not None:
            for k in by_kind:
                by_kind[k] = by_kind[k][:limit_per_kind]

        for kind, items in by_kind.items():
            logger.info("Will fetch %d %s pages", len(items), kind)

        # 2) Services (also produce content_chunks)
        for i, (url, slug, _) in enumerate(by_kind["service"], 1):
            try:
                html = await fetcher.get(url)
            except Exception as e:
                logger.warning("[service %d/%d] fetch failed for %s: %s", i, len(by_kind["service"]), url, e)
                continue
            svc = parse_service_page(url, slug, html)
            if svc is not None:
                services.append(svc)
            title = _title(html)
            content_chunks.extend(parse_faq_chunks(url, title, html))
            content_chunks.extend(parse_procedure_chunks(url, title, html))

        # 3) Doctors
        for i, (url, slug, _) in enumerate(by_kind["doctor"], 1):
            try:
                html = await fetcher.get(url)
            except Exception as e:
                logger.warning("[doctor %d/%d] fetch failed for %s: %s", i, len(by_kind["doctor"]), url, e)
                continue
            doc = parse_doctor_page(url, slug, html)
            if doc is not None:
                doctors.append(doc)

        # 4) Clinics (skip city aggregator pages, only fetch the leaf clinic detail URLs)
        leaf_clinics = [(url, slug, city) for (url, slug, city) in by_kind["clinic"] if city is not None]
        for i, (url, slug, city) in enumerate(leaf_clinics, 1):
            try:
                html = await fetcher.get(url)
            except Exception as e:
                logger.warning("[clinic %d/%d] fetch failed for %s: %s", i, len(leaf_clinics), url, e)
                continue
            cl = parse_clinic_page(url, city or "", slug, html)
            if cl is not None:
                clinics.append(cl)

        # 5) Content pages (why-dezy / how-it-works / cost / faqs / concern landings / etc.)
        for i, (url, slug, _) in enumerate(by_kind["content"], 1):
            try:
                html = await fetcher.get(url)
            except Exception as e:
                logger.warning("[content %d/%d] fetch failed for %s: %s", i, len(by_kind["content"]), url, e)
                continue
            content_chunks.extend(parse_content_page(url, slug, html))
            # Also surface FAQPage JSON-LD blocks if present
            title = _title(html)
            content_chunks.extend(parse_faq_chunks(url, title, html))

    snapshot = {
        "services": services,
        "doctors": doctors,
        "clinics": clinics,
        "content_chunks": content_chunks,
    }
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    logger.info(
        "Wrote snapshot: %s (services=%d, doctors=%d, clinics=%d, chunks=%d)",
        out_path, len(services), len(doctors), len(clinics), len(content_chunks),
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="/app/scripts/scrape_dezy/output/dezy_scrape.json",
        help="Path to write the JSON snapshot",
    )
    parser.add_argument(
        "--limit-per-kind",
        type=int,
        default=None,
        help="If set, only fetch this many URLs per (service/doctor/clinic) — useful for smoke tests",
    )
    args = parser.parse_args()
    asyncio.run(scrape(Path(args.out), limit_per_kind=args.limit_per_kind))
    return 0


if __name__ == "__main__":
    sys.exit(main())
