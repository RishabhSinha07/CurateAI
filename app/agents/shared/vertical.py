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

import uuid
from typing import TYPE_CHECKING, Any, MutableMapping, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.shared.response import ChatResponse

if TYPE_CHECKING:
    from app.db.repositories.session import SessionRepository


# Each vertical defines its own concrete state type (typically a TypedDict).
# The kernel passes state as a generic mapping; the vertical is responsible
# for narrowing it inside its own graph.
AgentStateLike = MutableMapping[str, Any]


@runtime_checkable
class Vertical(Protocol):
    """Contract every vertical implementation must satisfy.

    A vertical owns its agent graph end-to-end:

      1. `create_state` builds the initial state from generic kernel kwargs.
      2. `run` executes the graph and returns updated state.
      3. `finalize` does any vertical-specific persistence and produces both
         the wire response and the list of item IDs the kernel should store
         alongside the assistant message.

    The kernel handles session/message persistence and tenant resolution; it
    never inspects vertical-specific state keys.
    """

    name: str

    def create_state(
        self,
        *,
        session_id: uuid.UUID,
        user_message: str,
        existing_context: dict | None,
        existing_status: str,
        previous_response: str | None,
        tenant_id: uuid.UUID,
        tenant_enabled_domains: list[str],
        vertical_context_seed: dict | None = None,
    ) -> AgentStateLike:
        """Build the initial graph state for one conversation turn."""
        ...

    async def run(self, state: AgentStateLike, db: AsyncSession) -> AgentStateLike:
        """Execute one turn of the conversation graph."""
        ...

    async def finalize(
        self,
        state: AgentStateLike,
        session_repo: "SessionRepository",
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> tuple[ChatResponse, list[uuid.UUID]]:
        """Persist vertical-specific session state and build the wire response.

        Returns (response, item_ids) where item_ids are the UUIDs the kernel
        should attach to the assistant message (for analytics / refinement).
        """
        ...
