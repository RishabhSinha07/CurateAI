import pytest
from app.agents.router import router_agent
from app.db.session import async_session_factory

@pytest.mark.asyncio
async def test_router_wellness(base_state):
    base_state["user_message"] = "I'm feeling very tired lately"
    async with async_session_factory() as session:
        result = await router_agent(base_state, session)

        # Tiredness maps to energy/stamina or wellness — accept any valid energy domain
        assert result["domain_slug"] in [
            "wellness", "energy_stamina_vitality", "energy_stamina_performance",
            "multivitamins",
        ]
        assert result["next_agent"] in ["interviewer", "journey"]

@pytest.mark.asyncio
async def test_router_out_of_scope(base_state):
    base_state["user_message"] = "What is the capital of France?"
    async with async_session_factory() as session:
        result = await router_agent(base_state, session)

        assert result["domain_slug"] == "out_of_scope"
        assert result["next_agent"] == "fallback"  # out_of_scope routes to fallback, not safety


@pytest.mark.asyncio
async def test_router_awaiting_slot_override_prevents_fallback(base_state):
    """
    Single-word slot answers like "Vegetarian" must NEVER be routed to fallback
    when the session is awaiting_slot in a valid domain.

    Regression: session 5efc0345 — user answered "Vegetarian" to dietary preference
    question but was routed to fallback, returning food products instead of skin products.
    """
    base_state["user_message"] = "Vegetarian"
    base_state["status"] = "awaiting_slot"
    base_state["domain_slug"] = "skin_health_radiance"
    base_state["extracted_context"] = {
        "pending_slot_question": "What is your dietary preference? (e.g. vegan, vegetarian, no preference)",
        "graph_state": {
            "identified_problem": "dull_skin",
            "graph_domain": "skin_health_radiance",
            "filled_attributes": {},
            "questions_asked": 1,
        }
    }

    async with async_session_factory() as session:
        result = await router_agent(base_state, session)

    # Must stay in skin domain and go to interviewer — never fallback
    assert result["domain_slug"] == "skin_health_radiance", (
        f"Expected skin_health_radiance, got {result['domain_slug']!r}"
    )
    assert result["next_agent"] == "interviewer", (
        f"Expected interviewer, got {result['next_agent']!r}"
    )
    assert result.get("status") != "fallback_conversation"


@pytest.mark.asyncio
async def test_router_awaiting_slot_override_for_yes_no(base_state):
    """Yes/No answers while awaiting_slot must route to interviewer, not fallback."""
    base_state["user_message"] = "No"
    base_state["status"] = "awaiting_slot"
    base_state["domain_slug"] = "skin_health_radiance"
    base_state["extracted_context"] = {
        "pending_slot_question": "Do you have any allergies to supplements or ingredients?",
        "graph_state": {
            "identified_problem": "dull_skin",
            "graph_domain": "skin_health_radiance",
            "filled_attributes": {},
            "questions_asked": 1,
        }
    }

    async with async_session_factory() as session:
        result = await router_agent(base_state, session)

    assert result["domain_slug"] == "skin_health_radiance"
    assert result["next_agent"] == "interviewer"
    assert result.get("status") != "fallback_conversation"


@pytest.mark.asyncio
async def test_router_awaiting_slot_override_does_not_fire_for_ingredient_info(base_state):
    """
    The override must NOT suppress ingredient_info classification when the user
    asks a genuine educational question mid-interview.
    """
    base_state["user_message"] = "How does hyaluronic acid work?"
    base_state["status"] = "awaiting_slot"
    base_state["domain_slug"] = "skin_health_radiance"
    base_state["extracted_context"] = {
        "pending_slot_question": "What is your skin type?",
        "graph_state": {
            "identified_problem": "dull_skin",
            "graph_domain": "skin_health_radiance",
            "filled_attributes": {},
            "questions_asked": 1,
        }
    }

    async with async_session_factory() as session:
        result = await router_agent(base_state, session)

    # Should be classified as ingredient_info (not overridden to fallback)
    assert result["next_agent"] == "ingredient_info"
    assert result["intent_type"] == "ingredient_info"
