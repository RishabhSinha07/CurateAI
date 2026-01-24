import asyncio
import uuid
from app.db.session import async_session_factory
from app.agents.router import router_agent
from app.agents.state import AgentState

async def test_router():
    messages = [
        "I want to get rid of my dark spots",        # Should be skin-care/collagen
        "I'm feeling very tired lately",             # Should be energy/wellness
        "Do you have any vitamins for women?",       # Should be multivitamins/slow
        "What is the capital of France?"             # Should be out_of_scope
    ]

    print("🚀 Testing Router Agent...\n")

    async with async_session_factory() as session:
        for msg in messages:
            print(f"User Message: '{msg}'")
            
            # Initialize minimal state
            state: AgentState = {
                "session_id": uuid.uuid4(),
                "user_message": msg,
                "domain_id": None,
                "domain_slug": None,
                "domain_config": None,
                "extracted_context": {},
                "missing_slots": [],
                "search_results": [],
                "final_products": [],
                "response": None,
                "status": "active",
                "next_agent": None
            }
            
            try:
                # Run the agent
                result = await router_agent(state, session)
                
                print(f"  Result Domain: {result['domain_slug']}")
                print(f"  Next Agent:    {result['next_agent']}")
                print(f"  Status:       {result['status']}")
                print("-" * 30)
                
            except Exception as e:
                print(f"  ❌ Error: {e}")
                print("-" * 30)

if __name__ == "__main__":
    asyncio.run(test_router())
