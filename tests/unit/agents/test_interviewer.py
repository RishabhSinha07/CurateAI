import pytest
from app.agents.verticals.commerce.interviewer import interviewer_agent

@pytest.mark.asyncio
async def test_interviewer_problem_identification(base_state):
    base_state["domain_slug"] = "skin_health_radiance"
    base_state["user_message"] = "Help me with my skin"
    base_state["status"] = "collecting_info"
    
    result = await interviewer_agent(base_state)
    
    assert result["status"] == "awaiting_slot"
    assert "concern" in result["response"].lower() or "help" in result["response"].lower()

@pytest.mark.asyncio
async def test_interviewer_extraction(base_state):
    base_state["domain_slug"] = "skin_health_radiance"
    base_state["user_message"] = "acne"
    base_state["status"] = "awaiting_slot"
    base_state["response"] = "What is your primary skin concern?"
    
    result = await interviewer_agent(base_state)
    
    graph_state = result["extracted_context"].get("graph_state", {})
    # Note: This test assumes 'acne' exists in the graph as we added it previously
    assert graph_state.get("identified_problem") == "acne"
