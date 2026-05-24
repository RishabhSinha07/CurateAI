import pytest
from app.agents.verticals.commerce.safety import safety_agent

@pytest.mark.asyncio
async def test_safety_out_of_scope(base_state):
    base_state["domain_slug"] = "out_of_scope"
    base_state["user_message"] = "Tell me about cars"
    result = await safety_agent(base_state)
    
    assert any(word in result["response"].lower() for word in ["wellness", "supplement", "products", "help"])
    assert result["next_agent"] is None
