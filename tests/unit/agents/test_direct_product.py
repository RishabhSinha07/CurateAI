"""
Tests for the direct product query flow.

When a user asks for a specific product/ingredient by name (e.g., "I want melatonin"),
the system should bypass the interviewer and show results immediately.
"""
import pytest
from app.agents.router import router_agent
from app.agents.search import search_architect_agent
from app.agents.safety import safety_agent
from app.agents.interviewer import interviewer_agent
from app.agents.graph import after_router
from app.db.session import async_session_factory


# ── Router Tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_router_detects_direct_product(base_state):
    """Router should classify 'I want melatonin' as direct_product intent."""
    base_state["user_message"] = "I want melatonin"
    async with async_session_factory() as session:
        result = await router_agent(base_state, session)

    assert result["intent_type"] == "direct_product"
    assert result["next_agent"] == "search"
    assert result["extracted_context"].get("direct_search_term") is not None


@pytest.mark.asyncio
async def test_router_detects_vitamin_c_as_direct(base_state):
    """Router should classify 'show me vitamin C' as direct_product."""
    base_state["user_message"] = "show me vitamin C"
    async with async_session_factory() as session:
        result = await router_agent(base_state, session)

    assert result["intent_type"] == "direct_product"
    assert result["next_agent"] == "search"
    assert "vitamin" in result["extracted_context"]["direct_search_term"].lower()


@pytest.mark.asyncio
async def test_router_does_not_classify_symptom_as_direct(base_state):
    """Router should NOT classify symptoms as direct_product."""
    base_state["user_message"] = "I'm so tired all the time"
    async with async_session_factory() as session:
        result = await router_agent(base_state, session)

    assert result["intent_type"] != "direct_product"
    assert result["next_agent"] != "search"


# ── Graph Routing Tests ───────────────────────────────────────────────────────

def test_after_router_routes_to_search(base_state):
    """after_router should return 'search' when next_agent is 'search'."""
    base_state["next_agent"] = "search"
    assert after_router(base_state) == "search"


def test_after_router_still_routes_to_interviewer(base_state):
    """after_router should still route to interviewer for normal queries."""
    base_state["next_agent"] = "interviewer"
    assert after_router(base_state) == "interviewer"


def test_after_router_still_routes_to_journey(base_state):
    """after_router should still route to journey for journey intent."""
    base_state["next_agent"] = "journey"
    assert after_router(base_state) == "journey"


# ── Search Tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_uses_direct_search_term(base_state):
    """Search should use direct_search_term instead of knowledge graph query."""
    base_state["domain_slug"] = "sleep_stress_mental_calm"
    base_state["extracted_context"] = {
        "direct_search_term": "melatonin"
    }

    async with async_session_factory() as session:
        result = await search_architect_agent(base_state, session)

    assert result["next_agent"] == "reranker"
    assert result["status"] == "searching"
    assert len(result["search_results"]) > 0


@pytest.mark.asyncio
async def test_search_still_uses_graph_for_normal_queries(base_state):
    """Search should still use knowledge graph for normal problem-based queries."""
    base_state["domain_slug"] = "skin_health_radiance"
    base_state["extracted_context"] = {
        "graph_state": {
            "identified_problem": "dull_skin",
            "graph_domain": "skin_health_radiance",
            "filled_attributes": {}
        }
    }

    async with async_session_factory() as session:
        result = await search_architect_agent(base_state, session)

    assert result["next_agent"] == "reranker"
    assert result["status"] == "searching"


# ── Safety Tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_safety_direct_product_template_response(base_state):
    """Safety should return a template response for direct_product (no LLM call)."""
    base_state["intent_type"] = "direct_product"
    base_state["extracted_context"] = {"direct_search_term": "melatonin"}
    base_state["final_products"] = [
        {"id": "1", "name": "Restful Sleep", "description": "Melatonin supplement"}
    ]

    result = await safety_agent(base_state)

    assert "melatonin" in result["response"].lower()
    assert result["status"] == "awaiting_slot"
    assert "Personalise for me" in result["suggested_replies"]
    assert result["next_agent"] is None


@pytest.mark.asyncio
async def test_safety_direct_product_no_results(base_state):
    """Safety should handle no results gracefully for direct_product."""
    base_state["intent_type"] = "direct_product"
    base_state["extracted_context"] = {"direct_search_term": "xyz_nonexistent"}
    base_state["final_products"] = []

    result = await safety_agent(base_state)

    # Should hit the no-results handler (before the direct_product check)
    assert result["status"] == "completed"


# ── Interviewer Tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_interviewer_direct_product_asks_safety_questions(base_state):
    """Interviewer should ask global safety questions in direct product mode."""
    base_state["domain_slug"] = "sleep_stress_mental_calm"
    base_state["user_message"] = "Personalise for me"
    base_state["status"] = "awaiting_slot"
    base_state["extracted_context"] = {
        "direct_search_term": "melatonin"
    }

    result = await interviewer_agent(base_state)

    # Should ask a safety question (age, diet, allergies, etc.)
    assert result["status"] == "awaiting_slot"
    assert result["response"] is not None
    assert len(result["response"]) > 0


@pytest.mark.asyncio
async def test_interviewer_direct_product_routes_to_search_after_limit(base_state):
    """Interviewer should route to search after 3 safety questions."""
    base_state["domain_slug"] = "sleep_stress_mental_calm"
    base_state["user_message"] = "No allergies"
    base_state["status"] = "awaiting_slot"
    base_state["extracted_context"] = {
        "direct_search_term": "melatonin",
        "graph_state": {
            "questions_asked": 3,
            "filled_attributes": {
                "age_group": {"value": "26-35", "attribute_id": "age_group_26_35"},
                "diet": {"value": "non-vegetarian", "attribute_id": "diet_non_vegetarian"},
                "allergies": {"value": "none", "attribute_id": "allergy_none"},
            }
        }
    }

    result = await interviewer_agent(base_state)

    # Should route to search (hit the 3-question cap)
    assert result["next_agent"] == "search"
    assert result["status"] == "collecting_info"
