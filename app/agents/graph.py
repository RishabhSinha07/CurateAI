"""
LangGraph orchestration for the multi-agent consultation system.

Flow:
Entry → Router → Interviewer → [loop if missing slots]
                            ↓
                      Search Architect
                            ↓
                        Reranker
                            ↓
                         Safety → Output
"""

import uuid
from typing import Literal
from langgraph.graph import StateGraph, END
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.agents.router import router_agent
from app.agents.interviewer import interviewer_agent
from app.agents.search import search_architect_agent
from app.agents.reranker import reranker_agent
from app.agents.safety import safety_agent


def create_initial_state(
    session_id: uuid.UUID,
    user_message: str,
    existing_context: dict | None = None,
    existing_status: str = "active",
    domain_id: uuid.UUID | None = None,
    domain_slug: str | None = None,
    domain_config: dict | None = None,
) -> AgentState:
    """Create the initial state for a new conversation turn."""
    return AgentState(
        session_id=session_id,
        user_message=user_message,
        domain_id=domain_id,
        domain_slug=domain_slug,
        domain_config=domain_config,
        extracted_context=existing_context or {},
        missing_slots=[],
        search_results=[],
        final_products=[],
        response=None,
        status=existing_status,
        next_agent=None,
    )


async def router_node(state: AgentState, db: AsyncSession) -> AgentState:
    """Router agent node - classifies intent and assigns domain."""
    return await router_agent(state, db)


async def interviewer_node(state: AgentState) -> AgentState:
    """Interviewer agent node - extracts slots and asks clarifying questions."""
    return await interviewer_agent(state)


async def search_node(state: AgentState, db: AsyncSession) -> AgentState:
    """Search Architect agent node - expands query and performs hybrid search."""
    return await search_architect_agent(state, db)


async def reranker_node(state: AgentState) -> AgentState:
    """Reranker agent node - filters and ranks search results."""
    return await reranker_agent(state)


async def safety_node(state: AgentState) -> AgentState:
    """Safety agent node - generates final response with disclaimers."""
    return await safety_agent(state)


def should_route_to(state: AgentState) -> Literal["router", "interviewer"]:
    """
    Determine the entry point based on session status.

    If awaiting_slot, skip router and go directly to interviewer.
    Otherwise, start with router for intent classification.
    """
    if state.get("status") == "awaiting_slot":
        return "interviewer"
    return "router"


def after_interviewer(state: AgentState) -> Literal["search", "__end__"]:
    """
    Determine next step after interviewer.

    If still missing slots, end turn to wait for user input.
    If all slots filled, proceed to search.
    """
    next_agent = state.get("next_agent")
    if next_agent == "search":
        return "search"
    # If next_agent is None or not "search", we're waiting for user input
    return END


def after_router(state: AgentState) -> Literal["interviewer", "safety"]:
    """
    Determine next step after router.

    If out_of_scope, go to safety for graceful rejection.
    Otherwise, proceed to interviewer.
    """
    next_agent = state.get("next_agent")
    if next_agent == "safety":
        return "safety"
    return "interviewer"


class ConsultationGraph:
    """
    Manages the LangGraph state machine for product consultations.

    The graph is stateless - database session is passed per execution.
    """

    def __init__(self):
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the consultation state graph."""
        # Create the graph with AgentState schema
        builder = StateGraph(AgentState)

        # Add nodes (we'll wrap them to inject db later)
        builder.add_node("router", self._router_wrapper)
        builder.add_node("interviewer", self._interviewer_wrapper)
        builder.add_node("search", self._search_wrapper)
        builder.add_node("reranker", self._reranker_wrapper)
        builder.add_node("safety", self._safety_wrapper)

        # Set conditional entry point
        builder.set_conditional_entry_point(
            should_route_to,
            {
                "router": "router",
                "interviewer": "interviewer",
            }
        )

        # Add edges
        builder.add_conditional_edges(
            "router",
            after_router,
            {
                "interviewer": "interviewer",
                "safety": "safety",
            }
        )

        builder.add_conditional_edges(
            "interviewer",
            after_interviewer,
            {
                "search": "search",
                END: END,
            }
        )

        # Linear edges
        builder.add_edge("search", "reranker")
        builder.add_edge("reranker", "safety")
        builder.add_edge("safety", END)

        return builder.compile()

    async def _router_wrapper(self, state: AgentState) -> AgentState:
        """Wrapper to inject db session into router agent."""
        db = self._current_db
        return await router_node(state, db)

    async def _interviewer_wrapper(self, state: AgentState) -> AgentState:
        """Wrapper for interviewer agent."""
        return await interviewer_node(state)

    async def _search_wrapper(self, state: AgentState) -> AgentState:
        """Wrapper to inject db session into search agent."""
        db = self._current_db
        return await search_node(state, db)

    async def _reranker_wrapper(self, state: AgentState) -> AgentState:
        """Wrapper for reranker agent."""
        return await reranker_node(state)

    async def _safety_wrapper(self, state: AgentState) -> AgentState:
        """Wrapper for safety agent."""
        return await safety_node(state)

    async def run(self, state: AgentState, db: AsyncSession) -> AgentState:
        """
        Execute the consultation graph with the given state.

        Args:
            state: The current agent state
            db: Async database session for agents that need it

        Returns:
            The final state after graph execution
        """
        # Store db session for wrappers to access
        self._current_db = db

        # Run the graph
        result = await self.graph.ainvoke(state)

        return result


# Singleton instance
_consultation_graph: ConsultationGraph | None = None


def get_consultation_graph() -> ConsultationGraph:
    """Get or create the consultation graph singleton."""
    global _consultation_graph
    if _consultation_graph is None:
        _consultation_graph = ConsultationGraph()
    return _consultation_graph
