import pytest
from app.agents.verticals.commerce.reranker import reranker_agent

@pytest.mark.asyncio
async def test_reranker_agent_safety_filter(base_state):
    base_state["domain_slug"] = "skin_health_radiance"
    base_state["extracted_context"] = {
        "graph_state": {
            "identified_problem": "dull_skin",
            "graph_domain": "skin_health_radiance",
            "filled_attributes": {
                "diet": {"value": "vegan", "attribute_id": "diet_vegan"}
            }
        }
    }
    base_state["search_results"] = [
        {
            "id": "1",
            "name": "Marine Collagen",
            "attributes": {"ingredients": ["collagen_type_1_3_marine"]},
            "description": "Premium marine collagen for skin"
        },
        {
            "id": "2",
            "name": "Vegan Collagen Builder",
            "attributes": {"ingredients": ["vegan_collagen_builder"]},
            "description": "Plant-based skin support"
        }
    ]
    
    result = await reranker_agent(base_state)
    
    # Marine collagen should be filtered out for a vegan user
    assert result["next_agent"] == "safety"
    assert result["status"] == "ranked"
    assert len(result["final_products"]) == 1
    assert result["final_products"][0]["id"] == "2"
