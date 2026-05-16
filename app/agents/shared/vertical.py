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

from typing import Any, Mapping, MutableMapping, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession


# Each vertical defines its own concrete state type (typically a TypedDict).
# The kernel passes state as a generic mapping; the vertical is responsible
# for narrowing it inside its own graph.
AgentStateLike = MutableMapping[str, Any]


@runtime_checkable
class Vertical(Protocol):
    """Contract every vertical implementation must satisfy."""

    name: str

    async def run(self, state: AgentStateLike, db: AsyncSession) -> AgentStateLike:
        """Execute one turn of the conversation for this vertical."""
        ...
