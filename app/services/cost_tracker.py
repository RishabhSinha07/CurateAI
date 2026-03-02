"""
In-memory daily Bedrock cost accumulator per tenant.

Approximates cost from token estimates. Resets each calendar day (UTC).
"""

import time
from collections import defaultdict
from datetime import datetime, timezone


# Approximate cost per 1K tokens (input + output blended)
# Nova Pro: ~$0.0008/1K input, ~$0.0032/1K output
# Titan Embed: ~$0.0001/1K tokens
# Blended estimate: $0.002/1K tokens for LLM, $0.0001/1K for embeddings
COST_PER_1K_LLM_TOKENS_CENTS = 0.2  # $0.002 = 0.2 cents
COST_PER_EMBEDDING_CALL_CENTS = 0.01  # ~100 tokens * $0.0001/1K


class BedrockCostTracker:
    """Tracks approximate daily Bedrock costs per tenant."""

    def __init__(self):
        # {tenant_id: {"date": "2026-03-01", "cost_cents": 12.5}}
        self._daily: dict[str, dict] = defaultdict(lambda: {"date": "", "cost_cents": 0.0})

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _ensure_today(self, tenant_id: str) -> dict:
        """Reset counter if day has changed."""
        entry = self._daily[tenant_id]
        today = self._today()
        if entry["date"] != today:
            entry["date"] = today
            entry["cost_cents"] = 0.0
        return entry

    def record_llm_call(self, tenant_id: str, estimated_tokens: int = 2000) -> None:
        """Record an LLM invocation's approximate cost."""
        entry = self._ensure_today(tenant_id)
        entry["cost_cents"] += (estimated_tokens / 1000) * COST_PER_1K_LLM_TOKENS_CENTS

    def record_embedding_call(self, tenant_id: str) -> None:
        """Record an embedding call's approximate cost."""
        entry = self._ensure_today(tenant_id)
        entry["cost_cents"] += COST_PER_EMBEDDING_CALL_CENTS

    def get_daily_cost_cents(self, tenant_id: str) -> float:
        """Get current day's accumulated cost in cents."""
        entry = self._ensure_today(tenant_id)
        return entry["cost_cents"]

    def is_over_budget(self, tenant_id: str, cap_cents: int) -> bool:
        """Check if tenant has exceeded their daily budget."""
        return self.get_daily_cost_cents(tenant_id) >= cap_cents


# Module-level singleton
cost_tracker = BedrockCostTracker()
