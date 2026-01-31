import pytest
from app.agents.journey import journey_agent
from app.db.session import async_session_factory

@pytest.mark.asyncio
async def test_journey_agent_fallback(base_state):
    # Test that journey agent falls back to query flow if no matching journey found
    base_state["domain_slug"] = "wellness"
    base_state["user_message"] = "I need some basic vitamins"
    
    async with async_session_factory() as session:
        result = await journey_agent(base_state, session)
        
        # Should fall back to interviewer
        assert result["intent_type"] == "query"
        assert result["next_agent"] == "interviewer"
        assert result["status"] == "collecting_info"

@pytest.mark.asyncio
async def test_journey_agent_out_of_scope(base_state):
    # Test out of scope handling
    base_state["domain_slug"] = None
    
    async with async_session_factory() as session:
        result = await journey_agent(base_state, session)
        
        assert result["status"] == "out_of_scope"
        assert result["next_agent"] == "safety"
