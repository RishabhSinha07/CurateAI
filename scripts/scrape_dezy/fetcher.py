"""Rate-limited HTTP fetcher used by the dezy.com scraper."""

from __future__ import annotations

import asyncio
import logging

import httpx

USER_AGENT = "CurateAI-Onboarding/0.1 (+contact@curateai.dev)"
REQUEST_TIMEOUT_S = 30.0
DELAY_BETWEEN_REQUESTS_S = 1.5

logger = logging.getLogger(__name__)


class PoliteFetcher:
    """One-at-a-time async fetcher with a fixed delay between requests."""

    def __init__(self, delay: float = DELAY_BETWEEN_REQUESTS_S):
        self.delay = delay
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "PoliteFetcher":
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=REQUEST_TIMEOUT_S,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(self, url: str) -> str:
        assert self._client is not None, "use PoliteFetcher inside `async with`"
        async with self._lock:
            await asyncio.sleep(self.delay)
            logger.info("GET %s", url)
            resp = await self._client.get(url)
            resp.raise_for_status()
            return resp.text
