"""Dezy brand-supplied content (separate from the dezy.com scrape).

The scraper at `scripts/scrape_dezy/` reproduces what's on the public site.
This module holds the authoritative brand collateral Dezy hands us directly:
core promises, technology stack, network standards, awards, named-doctor
case counts, per-treatment positioning ("Dezy Advantage").

Both pipes produce JSON in the same shape so `scripts/ingest_dezy.py`
loads them with the same code path — only the `--snapshot` arg differs.
"""
