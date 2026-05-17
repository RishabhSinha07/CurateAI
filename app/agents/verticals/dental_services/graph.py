"""LangGraph orchestration for the dental_services vertical.

Topology mirrors the commerce graph in shape but uses dental-specific
intents:

                                ┌─ content_qa ─────────┐
                                ├─ comparison ─────────┤
                                ├─ doctor_search ──────┤
                                ├─ treatment_planner ──┤
    Entry → router ─────────────┤                       ├── safety ── END
                                ├─ interviewer →                     │
                                │     initial_treatments →           │
                                │     treatment_recommender          │
                                │                                    │
                                ├─ service_detail ─────┤
                                └─ fallback ───────────┘
                                  (also: refinement → loop back to router)

Each branch node sets state["response"] (and optionally items / cta_links),
then routes to the safety node which adds the persona disclaimer and the
default Book Consultation CTA. The interviewer/recommender path will
loop on awaiting_slot in Slice B.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Literal

from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.verticals.dental_services.comparison import comparison_agent
from app.agents.verticals.dental_services.content_qa import content_qa_agent
from app.agents.verticals.dental_services.doctor_search import doctor_search_agent
from app.agents.verticals.dental_services.fallback import fallback_agent
from app.agents.verticals.dental_services.initial_treatments import initial_treatments_agent
from app.agents.verticals.dental_services.interviewer import interviewer_agent
from app.agents.verticals.dental_services.refinement import refinement_agent
from app.agents.verticals.dental_services.router import router_agent
from app.agents.verticals.dental_services.safety import safety_agent
from app.agents.verticals.dental_services.service_detail import service_detail_agent
from app.agents.verticals.dental_services.state import DentalAgentState
from app.agents.verticals.dental_services.treatment_planner import treatment_planner_agent
from app.agents.verticals.dental_services.treatment_recommender import (
    treatment_recommender_agent,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Edge functions
# ---------------------------------------------------------------------------

BranchTarget = Literal[
    "interviewer",
    "content_qa",
    "comparison",
    "doctor_search",
    "treatment_planner",
    "service_detail",
    "fallback",
    "refinement",
]


def should_route_to(state: DentalAgentState) -> Literal["router", "refinement"]:
    """Entry-point: completed sessions go to refinement; everything else to router."""
    if state.get("status") == "completed":
        return "refinement"
    return "router"


def after_router(state: DentalAgentState) -> BranchTarget:
    next_agent = state.get("next_agent") or "fallback"
    if next_agent in (
        "interviewer", "content_qa", "comparison", "doctor_search",
        "treatment_planner", "service_detail", "fallback", "refinement",
    ):
        return next_agent  # type: ignore[return-value]
    return "fallback"


def after_interviewer(
    state: DentalAgentState,
) -> Literal["initial_treatments", "treatment_recommender", "safety", "__end__"]:
    """Slot loop:
       - more slots needed → END turn with awaiting_slot
       - all slots filled → on to recommender via initial_treatments
       - slice A stub always routes to initial_treatments
    """
    next_agent = state.get("next_agent")
    if next_agent == "initial_treatments":
        return "initial_treatments"
    if next_agent == "treatment_recommender":
        return "treatment_recommender"
    if next_agent == "safety":
        return "safety"
    return END


def after_refinement(state: DentalAgentState) -> Literal["router", "safety"]:
    if state.get("next_agent") == "router":
        return "router"
    return "safety"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


class DentalConsultationGraph:
    """LangGraph state machine for the dental_services vertical."""

    def __init__(self):
        self.graph = self._build_graph()
        self._current_db: AsyncSession | None = None

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(DentalAgentState)

        # Nodes — wrapped for timing + db injection where needed
        builder.add_node("router", self._router_wrapper)
        builder.add_node("interviewer", self._interviewer_wrapper)
        builder.add_node("initial_treatments", self._initial_treatments_wrapper)
        builder.add_node("treatment_recommender", self._treatment_recommender_wrapper)
        builder.add_node("content_qa", self._content_qa_wrapper)
        builder.add_node("doctor_search", self._doctor_search_wrapper)
        builder.add_node("comparison", self._comparison_wrapper)
        builder.add_node("treatment_planner", self._treatment_planner_wrapper)
        builder.add_node("service_detail", self._service_detail_wrapper)
        builder.add_node("refinement", self._refinement_wrapper)
        builder.add_node("fallback", self._fallback_wrapper)
        builder.add_node("safety", self._safety_wrapper)

        # Conditional entry: refinement when prior turn completed, else router.
        builder.set_conditional_entry_point(
            should_route_to,
            {"router": "router", "refinement": "refinement"},
        )

        # Router → one of the branch nodes
        builder.add_conditional_edges(
            "router",
            after_router,
            {
                "interviewer": "interviewer",
                "content_qa": "content_qa",
                "comparison": "comparison",
                "doctor_search": "doctor_search",
                "treatment_planner": "treatment_planner",
                "service_detail": "service_detail",
                "fallback": "fallback",
                "refinement": "refinement",
            },
        )

        # Interviewer loop
        builder.add_conditional_edges(
            "interviewer",
            after_interviewer,
            {
                "initial_treatments": "initial_treatments",
                "treatment_recommender": "treatment_recommender",
                "safety": "safety",
                END: END,
            },
        )

        # Refinement: either re-route to router or go straight to safety
        builder.add_conditional_edges(
            "refinement",
            after_refinement,
            {"router": "router", "safety": "safety"},
        )

        # Linear edges → safety → END
        builder.add_edge("initial_treatments", "treatment_recommender")
        builder.add_edge("treatment_recommender", "safety")
        builder.add_edge("content_qa", "safety")
        builder.add_edge("doctor_search", "safety")
        builder.add_edge("comparison", "safety")
        builder.add_edge("treatment_planner", "safety")
        builder.add_edge("service_detail", "safety")
        builder.add_edge("fallback", "safety")
        builder.add_edge("safety", END)

        return builder.compile()

    # ----- timing wrappers -----

    async def _timed(self, agent_name: str, coro) -> DentalAgentState:
        start = time.monotonic()
        result = await coro
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        logger.info(
            "agent_timing vertical=dental_services agent=%s duration_ms=%s "
            "session=%s status=%s next=%s",
            agent_name, duration_ms,
            result.get("session_id"), result.get("status"), result.get("next_agent"),
            extra={
                "agent": agent_name,
                "vertical": "dental_services",
                "duration_ms": duration_ms,
                "session_id": str(result.get("session_id")),
            },
        )
        return result

    async def _router_wrapper(self, state: DentalAgentState) -> DentalAgentState:
        return await self._timed("router", router_agent(state))

    async def _interviewer_wrapper(self, state: DentalAgentState) -> DentalAgentState:
        return await self._timed("interviewer", interviewer_agent(state))

    async def _initial_treatments_wrapper(self, state: DentalAgentState) -> DentalAgentState:
        return await self._timed("initial_treatments", initial_treatments_agent(state))

    async def _treatment_recommender_wrapper(self, state: DentalAgentState) -> DentalAgentState:
        return await self._timed("treatment_recommender", treatment_recommender_agent(state))

    async def _content_qa_wrapper(self, state: DentalAgentState) -> DentalAgentState:
        assert self._current_db is not None
        return await self._timed("content_qa", content_qa_agent(state, self._current_db))

    async def _doctor_search_wrapper(self, state: DentalAgentState) -> DentalAgentState:
        # doctor_search needs db
        assert self._current_db is not None
        return await self._timed("doctor_search", doctor_search_agent(state, self._current_db))

    async def _comparison_wrapper(self, state: DentalAgentState) -> DentalAgentState:
        return await self._timed("comparison", comparison_agent(state))

    async def _treatment_planner_wrapper(self, state: DentalAgentState) -> DentalAgentState:
        return await self._timed("treatment_planner", treatment_planner_agent(state))

    async def _service_detail_wrapper(self, state: DentalAgentState) -> DentalAgentState:
        return await self._timed("service_detail", service_detail_agent(state))

    async def _refinement_wrapper(self, state: DentalAgentState) -> DentalAgentState:
        return await self._timed("refinement", refinement_agent(state))

    async def _fallback_wrapper(self, state: DentalAgentState) -> DentalAgentState:
        return await self._timed("fallback", fallback_agent(state))

    async def _safety_wrapper(self, state: DentalAgentState) -> DentalAgentState:
        return await self._timed("safety", safety_agent(state))

    # ----- public entry -----

    async def run(self, state: DentalAgentState, db: AsyncSession) -> DentalAgentState:
        self._current_db = db
        try:
            return await self.graph.ainvoke(state)
        finally:
            self._current_db = None


_dental_graph: DentalConsultationGraph | None = None


def get_dental_graph() -> DentalConsultationGraph:
    global _dental_graph
    if _dental_graph is None:
        _dental_graph = DentalConsultationGraph()
    return _dental_graph
