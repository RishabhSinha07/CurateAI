"""Load a dezy.com scrape snapshot into the database.

Reads the JSON produced by `scripts.scrape_dezy.main` and upserts:

  - services       (with description_embedding, Titan v2 / 1024 dims)
  - doctors        (with bio_embedding when bio is present)
  - clinics
  - content_chunks (with embedding, the RAG corpus)

Usage:
    docker compose exec app python -m scripts.ingest_dezy \
        --snapshot /app/scripts/scrape_dezy/output/dezy_scrape.json \
        --tenant-id 11111111-1111-1111-1111-111111111111

Idempotent via the per-tenant unique constraints on slug / (source_url,
chunk_index). Reruns update existing rows in place.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Clinic, ContentChunk, Doctor, Service, Tenant
from app.db.session import async_session_factory
from app.services.embeddings import generate_embedding_async

logger = logging.getLogger("ingest_dezy")


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

async def _embed(text: str) -> list[float] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return await generate_embedding_async(text)
    except Exception as e:
        logger.warning("embedding failed for text len=%d: %s", len(text), e)
        return None


# ---------------------------------------------------------------------------
# Per-entity upserters
# ---------------------------------------------------------------------------

async def upsert_service(s: AsyncSession, tenant_id: uuid.UUID, row: dict) -> tuple[str, bool]:
    """Returns (slug, inserted_or_updated)."""
    existing = (
        await s.execute(
            select(Service).where(Service.tenant_id == tenant_id, Service.slug == row["slug"])
        )
    ).scalar_one_or_none()

    desc_for_embed = (row.get("description") or row.get("name") or row["slug"]).strip()
    embedding = await _embed(desc_for_embed)

    if existing is None:
        svc = Service(
            tenant_id=tenant_id,
            slug=row["slug"],
            name=row["name"],
            category=row["category"],
            subcategory=None,
            short_description=(row.get("description") or "")[:500] or None,
            description=row.get("description"),
            duration_minutes=None,
            recovery_period=None,
            price_min=row.get("price_min"),
            price_max=row.get("price_max"),
            currency=row.get("currency", "INR"),
            emi_eligible=False,
            url=row.get("url"),
            image_url=None,
            attributes={"source": "dezy.com"},
            description_embedding=embedding,
            is_active=True,
        )
        s.add(svc)
        return (row["slug"], True)

    existing.name = row["name"]
    existing.category = row["category"]
    existing.short_description = (row.get("description") or "")[:500] or None
    existing.description = row.get("description")
    existing.price_min = row.get("price_min")
    existing.price_max = row.get("price_max")
    existing.currency = row.get("currency", "INR")
    existing.url = row.get("url")
    existing.description_embedding = embedding
    existing.attributes = dict(existing.attributes or {}, source="dezy.com")
    existing.is_active = True
    return (row["slug"], False)


async def upsert_clinic(s: AsyncSession, tenant_id: uuid.UUID, row: dict) -> tuple[str, bool]:
    existing = (
        await s.execute(
            select(Clinic).where(Clinic.tenant_id == tenant_id, Clinic.slug == row["slug"])
        )
    ).scalar_one_or_none()

    if existing is None:
        cl = Clinic(
            tenant_id=tenant_id,
            slug=row["slug"],
            name=row["name"],
            address=row.get("address"),
            city=row.get("city"),
            state=None,
            postal_code=row.get("postal_code"),
            country="IN",
            attributes={"source": "dezy.com", "url": row.get("url")},
            is_active=True,
        )
        s.add(cl)
        return (row["slug"], True)

    existing.name = row["name"]
    existing.address = row.get("address") or existing.address
    existing.city = row.get("city") or existing.city
    existing.postal_code = row.get("postal_code") or existing.postal_code
    existing.attributes = dict(existing.attributes or {}, source="dezy.com", url=row.get("url"))
    existing.is_active = True
    return (row["slug"], False)


async def upsert_doctor(s: AsyncSession, tenant_id: uuid.UUID, row: dict) -> tuple[str, bool]:
    existing = (
        await s.execute(
            select(Doctor).where(Doctor.tenant_id == tenant_id, Doctor.slug == row["slug"])
        )
    ).scalar_one_or_none()

    embedding = await _embed(row.get("bio") or row.get("full_name") or row["slug"])

    attributes = {
        "source": "dezy.com",
        "url": row.get("url"),
        "rating": row.get("rating"),
        "cases_done": row.get("cases_done"),
    }

    if existing is None:
        doc = Doctor(
            tenant_id=tenant_id,
            slug=row["slug"],
            full_name=row["full_name"],
            gender=row.get("gender"),
            specializations=row.get("specializations") or [],
            city=row.get("city"),
            clinic_id=None,
            experience_years=row.get("experience_years"),
            credentials=row.get("credentials") or [],
            languages=row.get("languages") or [],
            bio=row.get("bio"),
            bio_url=row.get("url"),
            photo_url=None,
            attributes=attributes,
            bio_embedding=embedding,
            is_active=True,
        )
        s.add(doc)
        return (row["slug"], True)

    existing.full_name = row["full_name"]
    if row.get("gender") is not None:
        existing.gender = row["gender"]
    existing.specializations = row.get("specializations") or []
    existing.city = row.get("city") or existing.city
    if row.get("experience_years") is not None:
        existing.experience_years = row["experience_years"]
    existing.credentials = row.get("credentials") or []
    existing.languages = row.get("languages") or []
    existing.bio = row.get("bio") or existing.bio
    existing.bio_url = row.get("url") or existing.bio_url
    existing.attributes = {**(existing.attributes or {}), **attributes}
    existing.bio_embedding = embedding
    existing.is_active = True
    return (row["slug"], False)


async def upsert_chunk(s: AsyncSession, tenant_id: uuid.UUID, row: dict) -> tuple[str, bool]:
    existing = (
        await s.execute(
            select(ContentChunk).where(
                ContentChunk.tenant_id == tenant_id,
                ContentChunk.source_url == row["source_url"],
                ContentChunk.chunk_index == row["chunk_index"],
            )
        )
    ).scalar_one_or_none()

    embedding = await _embed(row["chunk_text"])

    key = f"{row['source_url']}#{row['chunk_index']}"
    if existing is None:
        ch = ContentChunk(
            tenant_id=tenant_id,
            source_url=row["source_url"],
            source_type=row.get("source_type", "page"),
            title=row.get("title"),
            chunk_text=row["chunk_text"],
            chunk_index=row["chunk_index"],
            token_count=len(row["chunk_text"].split()),
            embedding=embedding,
            chunk_metadata=row.get("metadata") or {},
            is_active=True,
        )
        s.add(ch)
        return (key, True)

    existing.source_type = row.get("source_type", existing.source_type)
    existing.title = row.get("title") or existing.title
    existing.chunk_text = row["chunk_text"]
    existing.token_count = len(row["chunk_text"].split())
    existing.embedding = embedding
    existing.chunk_metadata = row.get("metadata") or existing.chunk_metadata
    existing.is_active = True
    return (key, False)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def ingest(snapshot_path: Path, tenant_id: uuid.UUID, *, dry_run: bool = False) -> None:
    snapshot = json.loads(snapshot_path.read_text())
    counts = {"services": 0, "doctors": 0, "clinics": 0, "content_chunks": 0}
    inserted_counts = {"services": 0, "doctors": 0, "clinics": 0, "content_chunks": 0}

    async with async_session_factory() as session:
        # Verify the tenant exists and is dental_services
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise SystemExit(f"Tenant {tenant_id} not found")
        if tenant.vertical != "dental_services":
            raise SystemExit(
                f"Tenant {tenant_id} has vertical={tenant.vertical!r}, expected 'dental_services'"
            )

        logger.info("Ingesting into tenant %s (slug=%s)", tenant_id, tenant.slug)

        for kind, rows, upsert in (
            ("services", snapshot.get("services", []), upsert_service),
            ("clinics", snapshot.get("clinics", []), upsert_clinic),
            ("doctors", snapshot.get("doctors", []), upsert_doctor),
            ("content_chunks", snapshot.get("content_chunks", []), upsert_chunk),
        ):
            logger.info("Upserting %d %s ...", len(rows), kind)
            for i, row in enumerate(rows, 1):
                _, inserted = await upsert(session, tenant_id, row)
                counts[kind] += 1
                if inserted:
                    inserted_counts[kind] += 1
                if i % 20 == 0:
                    logger.info("  [%s] %d/%d", kind, i, len(rows))
                    await session.flush()

        if dry_run:
            logger.warning("--dry-run set: rolling back")
            await session.rollback()
        else:
            await session.commit()

    logger.info("Done. processed=%s inserted=%s", counts, inserted_counts)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", required=True, help="Path to the JSON snapshot")
    p.add_argument("--tenant-id", required=True, help="Tenant UUID (must have vertical=dental_services)")
    p.add_argument("--dry-run", action="store_true", help="Run upserts but roll back at the end")
    args = p.parse_args()

    asyncio.run(ingest(Path(args.snapshot), uuid.UUID(args.tenant_id), dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
