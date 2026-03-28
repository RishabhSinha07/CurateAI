"""
LangGraph orchestration for the multi-agent consultation system.

Flow:
                         ┌─ (journey intent) ──→ Journey → Safety ──→ END
                         │
Entry → Router ──────────┼─ (query) ─→ Interviewer ─→ (problem identified) ─→ Initial Products ─→ Interviewer ─→ [loop] ─┐
                         │                                                                                                  │
                         └─ (query + all filled) ──────→ Interviewer → Search → Reranker → Safety ─→ END

When the Router detects journey intent (e.g., "starting gym"), it routes directly to
the Journey agent which provides a complete product bundle with usage guidance.

For query intent, the Interviewer first asks the user to identify their problem/concern.
Once the problem is identified, initial products are fetched and shown alongside the
first slot-filling question.

Subsequent turns (status=awaiting_slot) skip Router entirely and go to the
Interviewer directly.
"""

import logging
import time
import uuid
from typing import Literal
from langgraph.graph import StateGraph, END
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.agents.state import AgentState
from app.agents.router import router_agent
from app.agents.initial_products import initial_products_agent
from app.agents.interviewer import interviewer_agent
from app.agents.search import search_architect_agent
from app.agents.reranker import reranker_agent
from app.agents.safety import safety_agent
from app.agents.refinement import refinement_agent
from app.agents.journey import journey_agent
from app.agents.fallback import fallback_agent
from app.agents.ingredient_info import ingredient_info_agent
from app.agents.product_detail import product_detail_agent


def create_initial_state(
    session_id: uuid.UUID,
    user_message: str,
    existing_context: dict | None = None,
    existing_status: str = "active",
    domain_slug: str | None = None,
    previous_response: str | None = None,
    tenant_id: uuid.UUID | None = None,
    tenant_enabled_domains: list[str] | None = None,
) -> AgentState:
    """Create the initial state for a new conversation turn."""
    ctx = existing_context or {}

    return AgentState(
        session_id=session_id,
        user_message=user_message,
        previous_domain_slug=domain_slug,  # Snapshot current domain for change detection
        domain_slug=domain_slug,
        extracted_context=ctx,
        missing_slots=[],
        initial_products=[],
        search_results=[],
        final_products=[],
        response=previous_response,  # Pass previous response for context
        suggested_replies=[],
        status=existing_status,
        next_agent=None,
        optional_slot_hint=None,
        tenant_id=tenant_id,
        tenant_enabled_domains=tenant_enabled_domains or ["*"],
        intent_type=None,
        journey_type=None,
        journey_bundle=None,
        product_context=None,
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


async def fallback_node(state: AgentState, db: AsyncSession) -> AgentState:
    """Fallback agent node - handles out-of-domain queries with catalog-wide search."""
    return await fallback_agent(state, db)


async def ingredient_info_node(state: AgentState) -> AgentState:
    """Ingredient info agent node - answers educational questions about ingredients."""
    return await ingredient_info_agent(state)


async def product_detail_node(state: AgentState, db: AsyncSession) -> AgentState:
    """Product detail agent node - answers questions about a specific shown product."""
    return await product_detail_agent(state, db)


def should_route_to(state: AgentState) -> Literal["router", "interviewer", "refinement", "fallback"]:
    """
    Determine the entry point based on session status.

    - awaiting_slot: Go to router so the LLM can decide whether the message
      is a slot answer (routes on to interviewer) or an ingredient question
      (routes to ingredient_info). The router receives the pending question as
      context so short answers like "yes" or "oily" are classified correctly.
    - fallback_conversation: Go to fallback (continuing out-of-domain conversation)
    - completed: Go to refinement (might be refining results or new topic)
    - Otherwise: Go to router for intent classification
    """
    status = state.get("status")

    if status == "fallback_conversation":
        return "fallback"
    if status == "completed":
        return "refinement"
    return "router"


def after_interviewer(state: AgentState) -> Literal["initial_products", "search", "safety", "__end__"]:
    """
    Determine next step after interviewer.

    If problem just identified → fetch initial products before asking slot questions.
    If still missing slots, end turn to wait for user input.
    If all slots filled, proceed to search.
    If user accepted initial products, skip to safety.
    """
    next_agent = state.get("next_agent")
    if next_agent == "initial_products":
        return "initial_products"
    if next_agent == "search":
        return "search"
    if next_agent == "safety":
        return "safety"
    # If next_agent is None, we're waiting for user input
    return END


def after_router(state: AgentState) -> Literal["interviewer", "journey", "safety", "search", "fallback", "ingredient_info", "refinement", "product_detail"]:
    """
    Determine next step after router.

    If fallback → fallback agent (out-of-domain catalog search).
    If journey intent → journey agent.
    If direct_product → search agent (bypass interviewer).
    If ingredient_info → ingredient_info agent (educational explanation).
    If product_detail → product detail agent (product-specific Q&A).
    If filter → refinement agent (filter initial products, then resume interview).
    Otherwise → interviewer (which will fetch initial products after
        identifying the user's problem).
    """
    next_agent = state.get("next_agent")

    if next_agent == "fallback":
        return "fallback"

    if next_agent == "safety":
        return "safety"

    if next_agent == "search":
        return "search"

    if next_agent == "journey":
        return "journey"

    if next_agent == "ingredient_info":
        return "ingredient_info"

    if next_agent == "product_detail":
        return "product_detail"

    if next_agent == "refinement":
        return "refinement"

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


def after_refinement(state: AgentState) -> Literal["search", "safety", "router", "interviewer", "ingredient_info", "product_detail"]:
    """
    Determine next step after refinement detection.

    If product_detail, answer a question about a specific shown product.
    If ingredient_info, answer the educational question without disrupting state.
    If refinement, filter in-memory and go to safety for response formatting.
    If re_personalize, go to interviewer to restart slot-filling for the same domain.
    If new topic, go to router for fresh classification.
    """
    next_agent = state.get("next_agent")
    if next_agent == "product_detail":
        return "product_detail"
    if next_agent == "ingredient_info":
        return "ingredient_info"
    if next_agent == "safety":
        return "safety"
    if next_agent == "search":
        return "search"
    if next_agent == "interviewer":
        return "interviewer"
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
        builder.add_node("fallback", self._fallback_wrapper)
        builder.add_node("ingredient_info", self._ingredient_info_wrapper)
        builder.add_node("product_detail", self._product_detail_wrapper)

        # Set conditional entry point
        builder.set_conditional_entry_point(
            should_route_to,
            {
                "router": "router",
                "interviewer": "interviewer",
                "refinement": "refinement",
                "fallback": "fallback",
            }
        )

        # Ingredient info: always end the turn.
        # Status is preserved by the agent, so the next user message
        # routes correctly (back to interviewer, refinement, etc.)
        builder.add_edge("ingredient_info", END)

        # Product detail: always end the turn.
        # Like ingredient_info, status is preserved so the next turn routes correctly.
        builder.add_edge("product_detail", END)

        # Add edges
        builder.add_conditional_edges(
            "router",
            after_router,
            {
                "interviewer": "interviewer",
                "journey": "journey",
                "safety": "safety",
                "search": "search",
                "fallback": "fallback",
                "ingredient_info": "ingredient_info",
                "product_detail": "product_detail",
                "refinement": "refinement",
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
                "initial_products": "initial_products",
                "search": "search",
                "safety": "safety",
                END: END,
            }
        )

        builder.add_conditional_edges(
            "refinement",
            after_refinement,
            {
                "product_detail": "product_detail",
                "ingredient_info": "ingredient_info",
                "search": "search",
                "safety": "safety",
                "router": "router",
                "interviewer": "interviewer",
            }
        )

        # Fallback always ends the turn (asked a question or completed with products)
        builder.add_edge("fallback", END)

        # Linear edges
        builder.add_edge("search", "reranker")
        builder.add_edge("reranker", "safety")
        builder.add_edge("safety", END)

        return builder.compile()

    async def _timed(self, agent_name: str, coro) -> AgentState:
        """Wrap an agent coroutine with timing and structured logging."""
        start = time.monotonic()
        result = await coro
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        logger.info(
            f"agent_timing agent={agent_name} duration_ms={duration_ms} "
            f"session={result.get('session_id')} status={result.get('status')} "
            f"next={result.get('next_agent')}",
            extra={
                "agent": agent_name,
                "duration_ms": duration_ms,
                "session_id": str(result.get("session_id")),
            },
        )
        return result

    async def _router_wrapper(self, state: AgentState) -> AgentState:
        return await self._timed("router", router_node(state, self._current_db))

    async def _initial_products_wrapper(self, state: AgentState) -> AgentState:
        return await self._timed("initial_products", initial_products_node(state, self._current_db))

    async def _interviewer_wrapper(self, state: AgentState) -> AgentState:
        return await self._timed("interviewer", interviewer_node(state))

    async def _search_wrapper(self, state: AgentState) -> AgentState:
        return await self._timed("search", search_node(state, self._current_db))

    async def _reranker_wrapper(self, state: AgentState) -> AgentState:
        return await self._timed("reranker", reranker_node(state))

    async def _safety_wrapper(self, state: AgentState) -> AgentState:
        return await self._timed("safety", safety_node(state))

    async def _refinement_wrapper(self, state: AgentState) -> AgentState:
        return await self._timed("refinement", refinement_node(state))

    async def _journey_wrapper(self, state: AgentState) -> AgentState:
        return await self._timed("journey", journey_node(state, self._current_db))

    async def _fallback_wrapper(self, state: AgentState) -> AgentState:
        return await self._timed("fallback", fallback_node(state, self._current_db))

    async def _ingredient_info_wrapper(self, state: AgentState) -> AgentState:
        return await self._timed("ingredient_info", ingredient_info_node(state))

    async def _product_detail_wrapper(self, state: AgentState) -> AgentState:
        return await self._timed("product_detail", product_detail_node(state, self._current_db))

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
