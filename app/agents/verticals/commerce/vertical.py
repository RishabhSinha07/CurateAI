"""Commerce vertical implementation.

Phase 0a wraps the existing `ConsultationGraph` unchanged. Later phases
will relocate the underlying agent modules into this package; for now we
delegate to the legacy location so behaviour is byte-identical.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.verticals.commerce.graph import get_consultation_graph
from app.agents.verticals.commerce.state import AgentState


class CommerceVertical:
    """Adapter that exposes the existing ConsultationGraph as a Vertical."""

    name = "commerce"

    async def run(self, state: AgentState, db: AsyncSession) -> AgentState:
        graph = get_consultation_graph()
        return await graph.run(state, db)
