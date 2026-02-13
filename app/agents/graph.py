"""
LangGraph orchestration for the multi-agent consultation system.

Flow:
                         ┌─ (journey intent) ──→ Journey → Safety ──→ END
                         │
Entry → Router ──────────┼─ (query + slots missing) ─→ Initial Products → Interviewer ─→ [loop] ─┐
                         │                                                                         │
                         └─ (query + all filled) ──────→ Interviewer → Search → Reranker → Safety ─→ END

When the Router detects journey intent (e.g., "starting gym"), it routes directly to
the Journey agent which provides a complete product bundle with usage guidance.

For query intent, the flow continues as before: if there are unfilled slots and the
domain just changed, show initial products while interviewing. Otherwise proceed
with search after collecting info.

Subsequent turns (status=awaiting_slot) skip Router entirely and go to the
Interviewer directly.
"""

import uuid
from typing import Literal
from langgraph.graph import StateGraph, END
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.agents.router import router_agent
from app.agents.initial_products import initial_products_agent
from app.agents.interviewer import interviewer_agent
from app.agents.search import search_architect_agent
from app.agents.reranker import reranker_agent
from app.agents.safety import safety_agent
from app.agents.refinement import refinement_agent
from app.agents.journey import journey_agent


def create_initial_state(
    session_id: uuid.UUID,
    user_message: str,
    existing_context: dict | None = None,
    existing_status: str = "active",
    domain_slug: str | None = None,
    previous_response: str | None = None,
) -> AgentState:
    """Create the initial state for a new conversation turn."""
    return AgentState(
        session_id=session_id,
        user_message=user_message,
        previous_domain_slug=domain_slug,  # Snapshot current domain for change detection
        domain_slug=domain_slug,
        extracted_context=existing_context or {},
        missing_slots=[],
        initial_products=[],
        search_results=[],
        final_products=[],
        response=previous_response,  # Pass previous response for context
        suggested_replies=[],
        status=existing_status,
        next_agent=None,
        optional_slot_hint=None,
        intent_type=None,
        journey_type=None,
        journey_bundle=None,
    )


async def router_node(state: AgentState, db: AsyncSession) -> AgentState:
    """Router agent node - classifies intent and assigns domain."""
    return await router_agent(state, db)


async def initial_products_node(state: AgentState, db: AsyncSession) -> AgentState:
    """Fetch a few domain products to show before the interview starts."""
    return await initial_products_agent(state, db)


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


async def refinement_node(state: AgentState) -> AgentState:
    """Refinement agent node - detects if user wants to refine results or new topic."""
    return await refinement_agent(state)


async def journey_node(state: AgentState, db: AsyncSession) -> AgentState:
    """Journey agent node - provides comprehensive product bundles for customer journeys."""
    return await journey_agent(state, db)


def should_route_to(state: AgentState) -> Literal["router", "interviewer", "refinement"]:
    """
    Determine the entry point based on session status.

    - awaiting_slot: Go to interviewer (answering a question)
    - completed: Go to refinement (might be refining results or new topic)
    - Otherwise: Go to router for intent classification
    """
    status = state.get("status")
    if status == "awaiting_slot":
        return "interviewer"
    if status == "completed":
        return "refinement"
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


def after_router(state: AgentState) -> Literal["initial_products", "interviewer", "journey", "safety"]:
    """
    Determine next step after router.

    If out_of_scope → safety.
    If journey intent → journey agent.
    If query intent and domain just changed AND problem identified →
        initial_products (show a few products while the interviewer gathers
        details).
    Otherwise → interviewer directly (no initial showcase).
    """
    next_agent = state.get("next_agent")

    if next_agent == "safety":
        return "safety"

    if next_agent == "journey":
        return "journey"

    domain_changed = state.get("domain_slug") != state.get("previous_domain_slug")

    # Check if we have a problem identified in the graph
    extracted_context = state.get("extracted_context", {})
    graph_state = extracted_context.get("graph_state", {})
    has_problem = bool(graph_state.get("identified_problem"))

    # If domain just changed and we have a problem, show initial products
    # while interviewer asks questions
    if domain_changed and has_problem:
        return "initial_products"

    return "interviewer"


def after_journey(state: AgentState) -> Literal["safety", "interviewer"]:
    """
    Determine next step after journey agent.
    
    If journey agent found products -> safety.
    If journey agent failed (no products) -> fallback to interviewer.
    """
    if state.get("next_agent") == "interviewer":
        return "interviewer"
    return "safety"


def after_refinement(state: AgentState) -> Literal["search", "router"]:
    """
    Determine next step after refinement detection.

    If refinement, go to search with updated constraints.
    If new topic, go to router for fresh classification.
    """
    next_agent = state.get("next_agent")
    if next_agent == "search":
        return "search"
    return "router"


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
        builder.add_node("initial_products", self._initial_products_wrapper)
        builder.add_node("interviewer", self._interviewer_wrapper)
        builder.add_node("search", self._search_wrapper)
        builder.add_node("reranker", self._reranker_wrapper)
        builder.add_node("safety", self._safety_wrapper)
        builder.add_node("refinement", self._refinement_wrapper)
        builder.add_node("journey", self._journey_wrapper)

        # Set conditional entry point
        builder.set_conditional_entry_point(
            should_route_to,
            {
                "router": "router",
                "interviewer": "interviewer",
                "refinement": "refinement",
            }
        )

        # Add edges
        builder.add_conditional_edges(
            "router",
            after_router,
            {
                "initial_products": "initial_products",
                "interviewer": "interviewer",
                "journey": "journey",
                "safety": "safety",
            }
        )

        # Journey conditional edge (safety or fallback to interviewer)
        builder.add_conditional_edges(
            "journey",
            after_journey,
            {
                "safety": "safety",
                "interviewer": "interviewer"
            }
        )

        # After fetching initial products, always proceed to interviewer
        builder.add_edge("initial_products", "interviewer")

        builder.add_conditional_edges(
            "interviewer",
            after_interviewer,
            {
                "search": "search",
                END: END,
            }
        )

        builder.add_conditional_edges(
            "refinement",
            after_refinement,
            {
                "search": "search",
                "router": "router",
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

    async def _initial_products_wrapper(self, state: AgentState) -> AgentState:
        """Wrapper to inject db session into initial products agent."""
        db = self._current_db
        return await initial_products_node(state, db)

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

    async def _refinement_wrapper(self, state: AgentState) -> AgentState:
        """Wrapper for refinement agent."""
        return await refinement_node(state)

    async def _journey_wrapper(self, state: AgentState) -> AgentState:
        """Wrapper to inject db session into journey agent."""
        db = self._current_db
        return await journey_node(state, db)

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
