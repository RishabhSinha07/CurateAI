"""LangGraph orchestration for the dental_services vertical.

Phase 1 is a single placeholder node so the routing seam can be exercised
end-to-end with the kernel. Phase 2 will build out the real topology:

    Entry -> Router -> {treatment_recommender | content_qa | doctor_search
                       | comparison | treatment_planner | service_detail
                       | clinical_escalation | refinement | fallback}
                    -> Safety -> END
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.verticals.dental_services.state import DentalAgentState


PLACEHOLDER_RESPONSE = (
    "Dezy's dental consultation agent is still warming up. The platform "
    "scaffolding is in place; full implant, aligner, and doctor-search "
    "flows land in the next phase."
)


async def placeholder_node(state: DentalAgentState) -> DentalAgentState:
    """Single Phase 1 node — returns a fixed placeholder response."""
    state["response"] = PLACEHOLDER_RESPONSE
    state["status"] = "active"
    state.setdefault("items", [])
    state.setdefault("cta_links", [])
    state.setdefault("suggested_replies", [])
    state.setdefault("extracted_context", {})
    return state


class DentalConsultationGraph:
    """Phase 1 graph — Entry -> placeholder -> END."""

    def __init__(self):
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(DentalAgentState)
        builder.add_node("placeholder", placeholder_node)
        builder.set_entry_point("placeholder")
        builder.add_edge("placeholder", END)
        return builder.compile()

    async def run(self, state: DentalAgentState) -> DentalAgentState:
        return await self.graph.ainvoke(state)


_dental_graph: DentalConsultationGraph | None = None


def get_dental_graph() -> DentalConsultationGraph:
    global _dental_graph
    if _dental_graph is None:
        _dental_graph = DentalConsultationGraph()
    return _dental_graph
