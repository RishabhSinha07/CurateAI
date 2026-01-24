import asyncio
import uuid
from app.agents.safety import safety_agent
from app.agents.state import AgentState


async def test_safety():
    """Test the Safety agent with various scenarios."""

    print("🚀 Testing Safety Agent...\n")

    # Mock final products from reranker
    mock_products = [
        {
            "id": str(uuid.uuid4()),
            "name": "Sleep Melts - Melatonin",
            "brand": "Wellbeing Nutrition",
            "description": "Natural sleep support with melatonin and chamomile.",
            "price": 29.99,
            "currency": "USD",
            "product_url": "https://example.com/sleep-melts",
            "image_url": "https://example.com/sleep-melts.jpg",
            "attributes": {"health_goal": "sleep"},
            "match_reasons": ["Matches your sleep goal", "Within budget", "Fast-dissolving format"],
            "rank": 1,
            "relevance_score": 0.95
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Calm & Relax Capsules",
            "brand": "Wellbeing Nutrition",
            "description": "Stress relief with ashwagandha.",
            "price": 35.00,
            "currency": "USD",
            "product_url": "https://example.com/calm",
            "image_url": "https://example.com/calm.jpg",
            "attributes": {"health_goal": "stress"},
            "match_reasons": ["Supports relaxation", "Natural ingredients"],
            "rank": 2,
            "relevance_score": 0.82
        },
    ]

    scenarios = [
        {
            "name": "Normal recommendation with products",
            "status": "ranked",
            "products": mock_products,
            "context": {"health_goal": "sleep", "budget": 50},
            "config": {"safety_disclaimers": ["Consult a healthcare provider before use."]},
        },
        {
            "name": "Out of scope request",
            "status": "out_of_scope",
            "products": [],
            "context": {},
            "config": {},
        },
        {
            "name": "No matching products found",
            "status": "ranked",
            "products": [],
            "context": {"health_goal": "rare_condition"},
            "config": {},
        },
    ]

    for scenario in scenarios:
        print(f"Scenario: {scenario['name']}")
        print(f"Status: {scenario['status']}")

        state: AgentState = {
            "session_id": uuid.uuid4(),
            "user_message": "Help me sleep better",
            "domain_id": uuid.uuid4(),
            "domain_slug": "melts",
            "domain_config": scenario["config"],
            "extracted_context": scenario["context"],
            "missing_slots": [],
            "search_results": [],
            "final_products": scenario["products"],
            "response": None,
            "status": scenario["status"],
            "next_agent": "safety"
        }

        try:
            result = await safety_agent(state)

            print(f"  Response Preview: {result['response'][:200]}...")
            print(f"  Final Status: {result['status']}")
            print(f"  Next Agent: {result['next_agent']}")
            print("-" * 50)

        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            print("-" * 50)


if __name__ == "__main__":
    asyncio.run(test_safety())
