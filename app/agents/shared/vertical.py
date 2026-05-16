"""The Vertical contract.

A Vertical packages everything that varies by business domain: the agent
graph, the catalog model it operates over, its tone, its slot schema, and
its knowledge graphs. The kernel knows nothing about specific verticals;
it dispatches to one via the registry based on `tenant.vertical`.

Phase 0a defines only the minimum surface (`name` + `run`) so the existing
Commerce flow can be plugged in unchanged. Later phases will extend this
protocol with `slot_schema`, `persona`, `item_types`, etc. as they become
load-bearing.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState


@runtime_checkable
class Vertical(Protocol):
    """Contract every vertical implementation must satisfy."""

    name: str

    async def run(self, state: AgentState, db: AsyncSession) -> AgentState:
        """Execute one turn of the conversation for this vertical."""
        ...
