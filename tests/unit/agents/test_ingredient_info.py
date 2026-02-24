"""
Tests for the ingredient info feature.

Covers three layers:
  1. Pure unit tests - helper functions (no LLM, no DB)
  2. Graph routing tests - should_route_to and after_router (no LLM, no DB)
  3. Integration tests - full ingredient_info_agent and router classification (LLM required)
"""

import uuid
import pytest

from app.agents.ingredient_info import (
    _build_user_context,
    _find_ingredients_in_graphs,
    _find_products_with_ingredient,
    ingredient_info_agent,
)
from app.agents.graph import (
    should_route_to,
    after_router,
)


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 – Helper functions (read from YAML, no LLM, no DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestFindIngredientsInGraphs:
    """_find_ingredients_in_graphs searches the YAML knowledge graphs."""

    def test_finds_collagen_variants(self):
        results = _find_ingredients_in_graphs("collagen")
        assert len(results) > 0
        names = [r.get("display_name", "").lower() for r in results]
        assert any("collagen" in n for n in names)

    def test_finds_vitamin_c(self):
        results = _find_ingredients_in_graphs("vitamin_c")
        assert len(results) > 0

    def test_returns_domain_key(self):
        results = _find_ingredients_in_graphs("collagen")
        assert all("domain" in r for r in results), (
            "Each result must include the 'domain' key from which it was found"
        )

    def test_returns_empty_for_unknown_ingredient(self):
        results = _find_ingredients_in_graphs("xxxxxxnonexistentingredient")
        assert results == []

    def test_no_duplicate_ingredient_ids(self):
        results = _find_ingredients_in_graphs("collagen")
        ids = [r.get("id") for r in results]
        assert len(ids) == len(set(ids)), "Duplicate ingredient IDs returned"


class TestFindProductsWithIngredient:
    """_find_products_with_ingredient matches products by name or description."""

    def test_matches_by_name(self):
        products = [
            {"name": "Marine Collagen Glow", "description": "A great supplement"},
            {"name": "Vitamin C Fizz", "description": "Energy boost"},
        ]
        matches = _find_products_with_ingredient("collagen", products)
        assert "Marine Collagen Glow" in matches

    def test_matches_by_description(self):
        products = [
            {"name": "Glow Formula", "description": "Contains marine collagen for skin"},
            {"name": "Energy Boost", "description": "B vitamins and iron"},
        ]
        matches = _find_products_with_ingredient("collagen", products)
        assert "Glow Formula" in matches

    def test_case_insensitive_match(self):
        products = [{"name": "Pure Collagen", "description": "COLLAGEN TYPE I"}]
        matches = _find_products_with_ingredient("Collagen", products)
        assert len(matches) > 0

    def test_returns_at_most_three(self):
        products = [
            {"name": f"Collagen Product {i}", "description": "collagen"}
            for i in range(10)
        ]
        matches = _find_products_with_ingredient("collagen", products)
        assert len(matches) <= 3

    def test_returns_empty_when_no_match(self):
        products = [{"name": "Vitamin D", "description": "Sunshine vitamin"}]
        matches = _find_products_with_ingredient("collagen", products)
        assert matches == []

    def test_handles_empty_product_list(self):
        matches = _find_products_with_ingredient("collagen", [])
        assert matches == []


# ─────────────────────────────────────────────────────────────────────────────
# Section 2b – _build_user_context (new helper, no LLM)
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildUserContext:
    """_build_user_context extracts domain, problem, and filled attributes from state."""

    def _make_state(self, **overrides):
        base = {
            "session_id": uuid.uuid4(),
            "user_message": "",
            "status": "active",
            "domain_slug": None,
            "previous_domain_slug": None,
            "extracted_context": {},
            "missing_slots": [],
            "initial_products": [],
            "search_results": [],
            "final_products": [],
            "response": None,
            "suggested_replies": [],
            "optional_slot_hint": None,
            "next_agent": None,
            "intent_type": None,
            "journey_type": None,
            "journey_bundle": None,
        }
        base.update(overrides)
        return base

    def test_returns_empty_string_when_no_context(self):
        state = self._make_state()
        assert _build_user_context(state) == ""

    def test_includes_domain_slug(self):
        state = self._make_state(domain_slug="skin_health_radiance")
        ctx = _build_user_context(state)
        assert "skin health radiance" in ctx

    def test_includes_identified_problem(self):
        state = self._make_state(
            extracted_context={
                "graph_state": {"identified_problem": "dull_skin"}
            }
        )
        ctx = _build_user_context(state)
        assert "dull skin" in ctx

    def test_includes_filled_attributes(self):
        state = self._make_state(
            extracted_context={
                "graph_state": {
                    "filled_attributes": {
                        "skin_type": {"value": "oily", "priority": 80},
                        "age": {"value": "28", "priority": 60},
                    }
                }
            }
        )
        ctx = _build_user_context(state)
        assert "skin type: oily" in ctx
        assert "age: 28" in ctx

    def test_skips_attributes_with_none_value(self):
        state = self._make_state(
            extracted_context={
                "graph_state": {
                    "filled_attributes": {
                        "skin_type": {"value": None},
                        "age": {"value": "30"},
                    }
                }
            }
        )
        ctx = _build_user_context(state)
        assert "skin type" not in ctx
        assert "age: 30" in ctx

    def test_combines_all_available_fields(self):
        state = self._make_state(
            domain_slug="hair_growth_density",
            extracted_context={
                "graph_state": {
                    "identified_problem": "hair_loss",
                    "filled_attributes": {
                        "diet": {"value": "vegan"},
                    },
                }
            },
        )
        ctx = _build_user_context(state)
        assert "hair growth density" in ctx
        assert "hair loss" in ctx
        assert "diet: vegan" in ctx

    def test_no_domain_but_has_problem(self):
        """domain_slug may be None while problem is already identified."""
        state = self._make_state(
            domain_slug=None,
            extracted_context={
                "graph_state": {"identified_problem": "low_energy"}
            },
        )
        ctx = _build_user_context(state)
        assert "low energy" in ctx
        assert "Current domain" not in ctx

    def test_handles_missing_graph_state_key(self):
        """extracted_context may exist without graph_state."""
        state = self._make_state(
            extracted_context={"candidate_problem": {"problem_id": "dull_skin"}}
        )
        # Should not raise; just returns whatever is available
        ctx = _build_user_context(state)
        assert isinstance(ctx, str)


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 – Graph routing (should_route_to, after_router)
# ─────────────────────────────────────────────────────────────────────────────

class TestShouldRouteTo:
    """should_route_to routes everything through the router except completed and fallback."""

    def _make_state(self, message: str, status: str = "active"):
        return {
            "session_id": uuid.uuid4(),
            "user_message": message,
            "status": status,
            "next_agent": None,
            "domain_slug": None,
            "previous_domain_slug": None,
            "extracted_context": {},
            "missing_slots": [],
            "initial_products": [],
            "search_results": [],
            "final_products": [],
            "response": None,
            "suggested_replies": [],
            "optional_slot_hint": None,
            "intent_type": None,
            "journey_type": None,
            "journey_bundle": None,
        }

    def test_awaiting_slot_routes_to_router(self):
        """Mid-interview messages always go through the router; the LLM decides the intent."""
        state = self._make_state("I have oily skin", status="awaiting_slot")
        assert should_route_to(state) == "router"

    def test_ingredient_question_mid_interview_routes_to_router(self):
        """Ingredient questions during the interview also go to the router."""
        state = self._make_state("How does collagen work?", status="awaiting_slot")
        assert should_route_to(state) == "router"

    def test_what_is_question_mid_interview_routes_to_router(self):
        state = self._make_state("What is vitamin C?", status="awaiting_slot")
        assert should_route_to(state) == "router"

    def test_completed_routes_to_refinement(self):
        state = self._make_state("Can I see cheaper options?", status="completed")
        assert should_route_to(state) == "refinement"

    def test_fallback_conversation_routes_to_fallback(self):
        state = self._make_state("Tell me more", status="fallback_conversation")
        assert should_route_to(state) == "fallback"

    def test_active_routes_to_router(self):
        state = self._make_state("I'm tired all the time", status="active")
        assert should_route_to(state) == "router"

    def test_collecting_info_routes_to_router(self):
        state = self._make_state("Benefits of zinc", status="collecting_info")
        assert should_route_to(state) == "router"


class TestAfterRouter:
    """after_router must include the ingredient_info path."""

    def _make_state(self, next_agent):
        return {
            "session_id": uuid.uuid4(),
            "user_message": "",
            "status": "active",
            "next_agent": next_agent,
            "domain_slug": None,
            "previous_domain_slug": None,
            "extracted_context": {},
            "missing_slots": [],
            "initial_products": [],
            "search_results": [],
            "final_products": [],
            "response": None,
            "suggested_replies": [],
            "optional_slot_hint": None,
            "intent_type": None,
            "journey_type": None,
            "journey_bundle": None,
        }

    def test_routes_ingredient_info_next_agent(self):
        state = self._make_state("ingredient_info")
        assert after_router(state) == "ingredient_info"

    def test_still_routes_to_search(self):
        assert after_router(self._make_state("search")) == "search"

    def test_still_routes_to_interviewer(self):
        assert after_router(self._make_state("interviewer")) == "interviewer"

    def test_still_routes_to_journey(self):
        assert after_router(self._make_state("journey")) == "journey"

    def test_still_routes_to_fallback(self):
        assert after_router(self._make_state("fallback")) == "fallback"


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 – Integration tests (LLM via AWS Bedrock)
# ─────────────────────────────────────────────────────────────────────────────

def _make_full_state(**overrides):
    base = {
        "session_id": uuid.uuid4(),
        "user_message": "How does collagen work?",
        "previous_domain_slug": None,
        "domain_slug": "skin_health_radiance",
        "extracted_context": {},
        "missing_slots": [],
        "initial_products": [],
        "search_results": [],
        "final_products": [],
        "response": None,
        "suggested_replies": [],
        "status": "completed",
        "next_agent": None,
        "optional_slot_hint": None,
        "intent_type": "ingredient_info",
        "journey_type": None,
        "journey_bundle": None,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_ingredient_info_agent_returns_response():
    """Agent must return a non-empty response string."""
    state = _make_full_state(user_message="How does collagen work?")
    result = await ingredient_info_agent(state)
    assert result["response"] is not None
    assert len(result["response"]) > 50


@pytest.mark.asyncio
async def test_ingredient_info_agent_response_mentions_ingredient():
    """Response must reference the queried ingredient."""
    state = _make_full_state(user_message="Why should I use vitamin C?")
    result = await ingredient_info_agent(state)
    assert "vitamin c" in result["response"].lower() or "vitamin" in result["response"].lower()


@pytest.mark.asyncio
async def test_ingredient_info_agent_preserves_status():
    """Agent must not change the session status."""
    for status in ("active", "collecting_info", "awaiting_slot", "completed"):
        state = _make_full_state(
            user_message="Tell me about magnesium",
            status=status,
        )
        result = await ingredient_info_agent(state)
        assert result["status"] == status, (
            f"Status changed from '{status}' to '{result['status']}'"
        )


@pytest.mark.asyncio
async def test_ingredient_info_agent_preserves_domain_and_context():
    """Agent must not change domain_slug or extracted_context."""
    ctx = {"graph_state": {"identified_problem": "dull_skin"}}
    state = _make_full_state(
        user_message="What does vitamin C do?",
        domain_slug="skin_health_radiance",
        extracted_context=ctx,
        status="awaiting_slot",
    )
    result = await ingredient_info_agent(state)

    assert result["domain_slug"] == "skin_health_radiance"
    assert result["extracted_context"] == ctx


@pytest.mark.asyncio
async def test_ingredient_info_agent_does_not_repeat_previous_response():
    """
    The agent must NOT append the previous assistant message to its response.
    Doing so caused the full previous response (initial products text, or the
    previous ingredient explanation) to bleed into every subsequent answer.
    """
    previous_response = "Here are some recommendations based on your concern."
    state = _make_full_state(
        user_message="How does collagen work?",
        status="awaiting_slot",
        response=previous_response,
    )
    result = await ingredient_info_agent(state)

    assert previous_response not in result["response"], (
        "Previous assistant message must not be appended to the ingredient explanation"
    )


@pytest.mark.asyncio
async def test_ingredient_info_agent_provides_resume_reply_when_awaiting_slot():
    """
    When status is awaiting_slot, suggested_replies must include a 'Continue'
    option so the user knows they can return to the interview flow.
    """
    state = _make_full_state(
        user_message="Tell me about magnesium",
        status="awaiting_slot",
        response="How old are you?",
        extracted_context={
            "graph_state": {"identified_problem": "dull_skin"},
            "pending_slot_question": "How old are you?",
        },
    )
    result = await ingredient_info_agent(state)
    assert any("continue" in r.lower() for r in result["suggested_replies"]), (
        f"Expected a 'Continue' reply when mid-interview, got: {result['suggested_replies']}"
    )


@pytest.mark.asyncio
async def test_ingredient_info_agent_provides_suggested_replies_when_completed():
    """When consultation is done, the agent should offer follow-up options."""
    state = _make_full_state(
        user_message="Benefits of zinc",
        status="completed",
    )
    result = await ingredient_info_agent(state)
    assert len(result["suggested_replies"]) > 0


@pytest.mark.asyncio
async def test_ingredient_info_agent_mentions_matching_product():
    """If a product in the current list contains the ingredient, it should be called out."""
    state = _make_full_state(
        user_message="How does collagen work?",
        status="completed",
        final_products=[
            {
                "id": "p1",
                "name": "Pure Marine Collagen",
                "description": "Marine collagen for skin elasticity",
            },
            {
                "id": "p2",
                "name": "Vitamin C Fizz",
                "description": "Effervescent vitamin C",
            },
        ],
    )
    result = await ingredient_info_agent(state)
    # The collagen product should be mentioned since the user asked about collagen
    assert "Pure Marine Collagen" in result["response"]


@pytest.mark.asyncio
async def test_ingredient_info_agent_works_without_products():
    """Agent must still return a valid response when no products are in state."""
    state = _make_full_state(
        user_message="What does hyaluronic acid do?",
        status="active",
        initial_products=[],
        final_products=[],
    )
    result = await ingredient_info_agent(state)
    assert result["response"] is not None
    assert len(result["response"]) > 20


@pytest.mark.asyncio
async def test_ingredient_info_agent_sets_next_agent_none():
    """next_agent must be None so the graph routes to END."""
    state = _make_full_state(user_message="How does collagen work?")
    result = await ingredient_info_agent(state)
    assert result["next_agent"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Section 4b – Contextual + compact response (new behaviour)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingredient_info_agent_response_is_compact():
    """
    Response (explanation only, before the pending-question footer) must be
    compact — roughly 3-4 sentences. We allow generous headroom (≤ 200 words)
    to avoid flakiness while still catching the old multi-paragraph behaviour.
    """
    state = _make_full_state(
        user_message="How does collagen work?",
        status="completed",
    )
    result = await ingredient_info_agent(state)

    # Strip the product-mention line and suggested-reply lines; count only the
    # main explanation portion.
    response_text = result["response"].split("\n\n")[0]  # first paragraph block
    word_count = len(response_text.split())
    assert word_count <= 200, (
        f"Response is too long ({word_count} words). Expected ≤ 200 words. "
        f"Response: {response_text!r}"
    )


@pytest.mark.asyncio
async def test_ingredient_info_agent_uses_identified_problem_context():
    """
    When the session has an identified_problem, the LLM receives that context.
    The response should not be a generic all-audience explanation but should
    at least stay relevant to the skin/glow domain without hallucinating.
    We verify the agent completes without error and returns a non-empty string —
    the contextual grounding is in the prompt, not the assertion.
    """
    state = _make_full_state(
        user_message="Why should I use vitamin C?",
        domain_slug="skin_health_radiance",
        extracted_context={
            "graph_state": {
                "identified_problem": "dull_skin",
                "graph_domain": "skin_health_radiance",
                "filled_attributes": {
                    "skin_type": {"value": "oily", "attribute_id": "a1", "priority": 80}
                },
                "questions_asked": 1,
            }
        },
        status="collecting_info",
    )
    result = await ingredient_info_agent(state)

    assert result["response"] is not None
    assert len(result["response"]) > 30
    # Status and context must be unchanged
    assert result["status"] == "collecting_info"
    assert result["domain_slug"] == "skin_health_radiance"


@pytest.mark.asyncio
async def test_ingredient_info_agent_preserves_awaiting_slot_status_through_router():
    """
    Regression test for the router status-clobber bug.

    When status=awaiting_slot and the user asks an ingredient question,
    the router used to unconditionally set status='collecting_info' before
    checking the intent type. After the fix the status must remain 'awaiting_slot'
    so the interrupted slot question resumes correctly on the next turn.
    """
    from app.agents.router import router_agent
    from app.db.session import async_session_factory

    state = _make_full_state(
        user_message="How does collagen work?",
        status="awaiting_slot",
        domain_slug="skin_health_radiance",
        extracted_context={
            "graph_state": {
                "identified_problem": "dull_skin",
                "filled_attributes": {"skin_type": {"value": "oily"}},
            }
        },
        response="Do you have any allergies? (Yes / No / Prefer not to say)",
    )

    async with async_session_factory() as session:
        router_result = await router_agent(state, session)

    # Router must classify as ingredient_info
    assert router_result["intent_type"] == "ingredient_info"
    assert router_result["next_agent"] == "ingredient_info"
    # Status must NOT be overwritten — the slot question must still be resumable
    assert router_result["status"] == "awaiting_slot", (
        f"Router clobbered status to '{router_result['status']}' — "
        "ingredient_info routing must preserve the original status"
    )


@pytest.mark.asyncio
async def test_ingredient_info_agent_what_is_question_triggers_after_initial_products():
    """
    Regression test: with status=awaiting_slot, ingredient questions must reach
    the ingredient_info agent. The router (LLM) classifies the intent — no
    heuristic prefix list is involved. Verifies the full agent produces a valid response
    without repeating the previous slot question.
    """
    pending_slot_q = "What is your skin type? (Oily / Dry / Combination / Normal)"
    state = _make_full_state(
        user_message="What is hyaluronic acid?",
        status="awaiting_slot",
        domain_slug="skin_health_radiance",
        extracted_context={
            "graph_state": {
                "identified_problem": "dull_skin",
                "filled_attributes": {},
            }
        },
        response=pending_slot_q,
    )
    result = await ingredient_info_agent(state)

    assert result["response"] is not None
    assert len(result["response"]) > 30
    # Status must be preserved
    assert result["status"] == "awaiting_slot"
    # Pending slot question must NOT be appended (user sees it in conversation history)
    assert pending_slot_q not in result["response"]


@pytest.mark.asyncio
async def test_ingredient_info_agent_uses_filled_attributes_context():
    """
    When diet and allergy slots are filled, the agent has enough context to
    tailor its explanation. Response must still be non-empty and compact.
    """
    state = _make_full_state(
        user_message="What does collagen do?",
        domain_slug="skin_health_radiance",
        extracted_context={
            "graph_state": {
                "identified_problem": "dull_skin",
                "filled_attributes": {
                    "diet": {"value": "vegan"},
                    "age": {"value": "32"},
                },
            }
        },
        status="awaiting_slot",
        response="Do you have any allergies?",
    )
    result = await ingredient_info_agent(state)

    response_text = result["response"]
    assert response_text is not None
    word_count = len(response_text.split())
    assert word_count <= 200, (
        f"Response too long with context ({word_count} words)"
    )
    # Pending question must NOT appear — the user sees it in conversation history
    assert "Do you have any allergies?" not in response_text


# ─────────────────────────────────────────────────────────────────────────────
# Section 5 – Router integration: ingredient_info intent classification
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_router_classifies_how_does_as_ingredient_info(base_state):
    """Router must classify 'How does collagen work?' as ingredient_info."""
    from app.agents.router import router_agent
    from app.db.session import async_session_factory

    base_state["user_message"] = "How does collagen work?"
    async with async_session_factory() as session:
        result = await router_agent(base_state, session)

    assert result["intent_type"] == "ingredient_info"
    assert result["next_agent"] == "ingredient_info"


@pytest.mark.asyncio
async def test_router_classifies_benefits_as_ingredient_info(base_state):
    """Router must classify 'Benefits of zinc' as ingredient_info."""
    from app.agents.router import router_agent
    from app.db.session import async_session_factory

    base_state["user_message"] = "Benefits of zinc for skin"
    async with async_session_factory() as session:
        result = await router_agent(base_state, session)

    assert result["intent_type"] == "ingredient_info"
    assert result["next_agent"] == "ingredient_info"


@pytest.mark.asyncio
async def test_router_distinguishes_ingredient_info_from_direct_product(base_state):
    """
    'How does collagen work?' is ingredient_info.
    'Show me collagen' is direct_product.
    The router must not confuse the two.
    """
    from app.agents.router import router_agent
    from app.db.session import async_session_factory

    base_state["user_message"] = "Show me collagen products"
    async with async_session_factory() as session:
        result = await router_agent(base_state, session)

    assert result["intent_type"] == "direct_product"
    assert result["next_agent"] == "search"


@pytest.mark.asyncio
async def test_router_still_classifies_symptom_as_query(base_state):
    """Symptom descriptions must not be reclassified as ingredient_info."""
    from app.agents.router import router_agent
    from app.db.session import async_session_factory

    base_state["user_message"] = "I have dull skin and want to improve my glow"
    async with async_session_factory() as session:
        result = await router_agent(base_state, session)

    assert result["intent_type"] == "query"
    assert result["next_agent"] == "interviewer"
