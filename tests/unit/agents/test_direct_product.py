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
async def test_safety_direct_product_llm_response(base_state):
    """Safety should return an LLM-generated response for direct_product with benefits."""
    from unittest.mock import AsyncMock, patch
    from app.agents.safety import SafetyResponse

    mock_result = SafetyResponse(
        response="**Melatonin** is a naturally occurring hormone known to support your body's sleep-wake cycle. It may help with falling asleep faster and improving overall sleep quality. Look for products with clear dosage info to find the right fit for your routine.",
        disclaimers=[],
        contains_medical_claims=False,
        is_safe=True,
    )
    mock_model = AsyncMock()
    mock_model.ainvoke.return_value = mock_result

    base_state["intent_type"] = "direct_product"
    base_state["extracted_context"] = {"direct_search_term": "melatonin"}
    base_state["final_products"] = [
        {"id": "1", "name": "Restful Sleep", "brand": "NatureCo", "description": "Melatonin supplement"}
    ]

    with patch("app.agents.safety.get_safety_model", return_value=mock_model):
        result = await safety_agent(base_state)

    assert "melatonin" in result["response"].lower()
    assert "sleep" in result["response"].lower()
    assert result["status"] == "awaiting_slot"
    assert "Personalise for me" in result["suggested_replies"]
    assert result["next_agent"] is None
    # Should still have disclaimers appended
    assert "FDA" in result["response"]
    mock_model.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_safety_direct_product_llm_fallback(base_state):
    """Safety should fall back to template if LLM call fails."""
    from unittest.mock import AsyncMock, patch

    mock_model = AsyncMock()
    mock_model.ainvoke.side_effect = Exception("LLM unavailable")

    base_state["intent_type"] = "direct_product"
    base_state["extracted_context"] = {"direct_search_term": "melatonin"}
    base_state["final_products"] = [
        {"id": "1", "name": "Restful Sleep", "description": "Melatonin supplement"}
    ]

    with patch("app.agents.safety.get_safety_model", return_value=mock_model):
        result = await safety_agent(base_state)

    assert "melatonin" in result["response"].lower()
    assert result["status"] == "awaiting_slot"
    assert "Personalise for me" in result["suggested_replies"]
    assert "FDA" in result["response"]


@pytest.mark.asyncio
async def test_safety_direct_product_includes_match_reasons_in_prompt(base_state):
    """Safety should pass product match reasons to the LLM prompt."""
    from unittest.mock import AsyncMock, patch, call
    from app.agents.safety import SafetyResponse

    mock_result = SafetyResponse(
        response="**Vitamin C** is known to support immune function and may help with skin radiance.",
        disclaimers=[],
        contains_medical_claims=False,
        is_safe=True,
    )
    mock_model = AsyncMock()
    mock_model.ainvoke.return_value = mock_result

    base_state["intent_type"] = "direct_product"
    base_state["extracted_context"] = {"direct_search_term": "vitamin C"}
    base_state["final_products"] = [
        {"id": "1", "name": "C-1000", "brand": "PureVit", "match_reasons": ["High potency vitamin C", "Immune support"]},
        {"id": "2", "name": "C Complex", "brand": "NutraLife", "match_reasons": "Buffered vitamin C"},
    ]

    with patch("app.agents.safety.get_safety_model", return_value=mock_model):
        result = await safety_agent(base_state)

    # Verify the LLM prompt includes product context
    prompt_sent = mock_model.ainvoke.call_args[0][0]
    assert "C-1000" in prompt_sent
    assert "PureVit" in prompt_sent
    assert "High potency vitamin C" in prompt_sent
    assert "Buffered vitamin C" in prompt_sent


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
