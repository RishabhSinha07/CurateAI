import pytest
from app.agents.router import router_agent
from app.db.session import async_session_factory

@pytest.mark.asyncio
async def test_router_wellness(base_state):
    base_state["user_message"] = "I'm feeling very tired lately"
    async with async_session_factory() as session:
        result = await router_agent(base_state, session)
        
        assert result["domain_slug"] in ["wellness", "multivitamins"]
        assert result["next_agent"] in ["interviewer", "journey"]

@pytest.mark.asyncio
async def test_router_out_of_scope(base_state):
    base_state["user_message"] = "What is the capital of France?"
    async with async_session_factory() as session:
        result = await router_agent(base_state, session)
        
        assert result["domain_slug"] == "out_of_scope"
        assert result["next_agent"] == "safety"
