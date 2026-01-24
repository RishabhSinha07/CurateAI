import asyncio
import uuid
from app.db.session import async_session_factory
from app.db.repositories.domain import DomainRepository
from app.agents.search import search_architect_agent
from app.agents.state import AgentState


async def test_search_architect():
    """Test the Search Architect agent with various contexts."""

    print("🚀 Testing Search Architect Agent...\n")

    async with async_session_factory() as session:
        # Get a real domain for testing
        domain_repo = DomainRepository(session)
        domains = await domain_repo.get_all_active()

        if not domains:
            print("❌ No domains found. Please seed the database first.")
            return

        # Use the first domain with products
        test_domain = domains[0]
        domain_config = test_domain.get_merged_config()

        scenarios = [
            {
                "name": "Sleep supplements search",
                "message": "I need something to help me sleep better",
                "context": {"health_goal": "sleep"},
                "domain_slug": test_domain.slug,
            },
            {
                "name": "Skin health with budget",
                "message": "Looking for collagen under $50",
                "context": {"skin_concern": "anti-aging", "budget": 50},
                "domain_slug": test_domain.slug,
            },
            {
                "name": "Energy and immunity",
                "message": "I want more energy and better immunity",
                "context": {"health_goal": "energy"},
                "domain_slug": test_domain.slug,
            },
        ]

        for scenario in scenarios:
            print(f"Scenario: {scenario['name']}")
            print(f"Context: {scenario['context']}")

            state: AgentState = {
                "session_id": uuid.uuid4(),
                "user_message": scenario["message"],
                "domain_id": test_domain.id,
                "domain_slug": scenario["domain_slug"],
                "domain_config": domain_config,
                "extracted_context": scenario["context"],
                "missing_slots": [],
                "search_results": [],
                "final_products": [],
                "response": None,
                "status": "collecting_info",
                "next_agent": "search"
            }

            try:
                result = await search_architect_agent(state, session)

                print(f"  Found {len(result['search_results'])} products")
                print(f"  Next Agent: {result['next_agent']}")

                # Show top 3 results
                for i, product in enumerate(result['search_results'][:3]):
                    print(f"  {i+1}. {product['name']} (similarity: {product['similarity_score']:.2f})")

                print("-" * 40)

            except Exception as e:
                print(f"  ❌ Error: {e}")
                import traceback
                traceback.print_exc()
                print("-" * 40)


if __name__ == "__main__":
    asyncio.run(test_search_architect())
