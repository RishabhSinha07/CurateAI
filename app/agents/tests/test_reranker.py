import asyncio
import uuid
from app.agents.reranker import reranker_agent
from app.agents.state import AgentState


async def test_reranker():
    """Test the Reranker agent with mock search results."""

    print("🚀 Testing Reranker Agent...\n")

    # Mock search results (simulating what search_architect would return)
    mock_search_results = [
        {
            "id": str(uuid.uuid4()),
            "name": "Sleep Melts - Melatonin",
            "brand": "Wellbeing Nutrition",
            "description": "Natural sleep support with melatonin and chamomile for better rest.",
            "price": 29.99,
            "currency": "USD",
            "product_url": "https://example.com/sleep-melts",
            "image_url": "https://example.com/sleep-melts.jpg",
            "attributes": {"health_goal": "sleep", "format": "melts"},
            "similarity_score": 0.89
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Calm & Relax Capsules",
            "brand": "Wellbeing Nutrition",
            "description": "Stress relief and relaxation support with ashwagandha.",
            "price": 45.00,
            "currency": "USD",
            "product_url": "https://example.com/calm-capsules",
            "image_url": "https://example.com/calm.jpg",
            "attributes": {"health_goal": "stress", "format": "capsules"},
            "similarity_score": 0.75
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Premium Sleep Complex",
            "brand": "Wellbeing Nutrition",
            "description": "Advanced formula for deep, restorative sleep.",
            "price": 65.00,
            "currency": "USD",
            "product_url": "https://example.com/premium-sleep",
            "image_url": "https://example.com/premium-sleep.jpg",
            "attributes": {"health_goal": "sleep", "format": "capsules"},
            "similarity_score": 0.82
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Energy Boost Melts",
            "brand": "Wellbeing Nutrition",
            "description": "Natural energy with B-vitamins and green tea extract.",
            "price": 24.99,
            "currency": "USD",
            "product_url": "https://example.com/energy-melts",
            "image_url": "https://example.com/energy.jpg",
            "attributes": {"health_goal": "energy", "format": "melts"},
            "similarity_score": 0.45
        },
    ]

    scenarios = [
        {
            "name": "Sleep products with budget constraint",
            "context": {"health_goal": "sleep", "budget": 40},
            "message": "I need something for sleep under $40"
        },
        {
            "name": "Sleep products preferring capsules",
            "context": {"health_goal": "sleep", "format_preference": "capsules"},
            "message": "I want sleep supplements in capsule form"
        },
        {
            "name": "No specific constraints",
            "context": {"health_goal": "sleep"},
            "message": "Help me sleep better"
        },
    ]

    for scenario in scenarios:
        print(f"Scenario: {scenario['name']}")
        print(f"Context: {scenario['context']}")

        state: AgentState = {
            "session_id": uuid.uuid4(),
            "user_message": scenario["message"],
            "domain_id": uuid.uuid4(),
            "domain_slug": "melts",
            "domain_config": {"required_slots": ["health_goal"]},
            "extracted_context": scenario["context"],
            "missing_slots": [],
            "search_results": mock_search_results,
            "final_products": [],
            "response": None,
            "status": "searching",
            "next_agent": "reranker"
        }

        try:
            result = await reranker_agent(state)

            print(f"  Selected {len(result['final_products'])} products:")
            for i, product in enumerate(result['final_products']):
                print(f"  {i+1}. {product['name']} - ${product['price']}")
                print(f"      Reasons: {', '.join(product.get('match_reasons', []))}")

            print(f"  Next Agent: {result['next_agent']}")
            print(f"  Status: {result['status']}")
            print("-" * 40)

        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            print("-" * 40)


if __name__ == "__main__":
    asyncio.run(test_reranker())
