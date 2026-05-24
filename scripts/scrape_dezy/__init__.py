"""Polite scraper for dezy.com.

Reads the public sitemap, fetches service / doctor / clinic / FAQ pages
with conservative rate limiting, and emits a normalized JSON snapshot
that `scripts.ingest_dezy` can load into the database.

robots.txt was checked (see Phase 3 onboarding notes): dezy.com
explicitly allows AI crawlers including ClaudeBot. We set a clear
User-Agent identifying ourselves, cap concurrency to 1, sleep between
requests, and obey the sitemap as our crawl boundary.
"""
