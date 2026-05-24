import pytest
from app.agents.verticals.commerce.search import search_architect_agent
from app.db.session import async_session_factory

@pytest.mark.asyncio
async def test_search_agent(base_state):
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
