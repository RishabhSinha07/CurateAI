import asyncio
import uuid
from app.agents.interviewer import interviewer_agent
from app.agents.state import AgentState

async def test_interviewer():
    # Mock some scenarios
    scenarios = [
        {
            "name": "Initial extraction (Skin Type provided)",
            "message": "I have oily skin and I'm looking for a serum.",
            "config": {"required_slots": ["skin_type", "skin_concern"]},
            "context": {}
        },
        {
            "name": "Follow-up question (Concern provided)",
            "message": "It's for dark spots.",
            "config": {"required_slots": ["skin_type", "skin_concern"]},
            "context": {"skin_type": "oily"}
        },
        {
            "name": "All slots filled",
            "message": "My skin is dry and I have sensitivity issues.",
            "config": {"required_slots": ["skin_type", "sensitivity"]},
            "context": {}
        }
    ]

    print("🚀 Testing Interviewer Agent...\n")

    for scenario in scenarios:
        print(f"Scenario: {scenario['name']}")
        print(f"User Message: '{scenario['message']}'")
        
        state: AgentState = {
            "session_id": uuid.uuid4(),
            "user_message": scenario['message'],
            "domain_id": uuid.uuid4(),
            "domain_slug": "skin-care",
            "domain_config": scenario['config'],
            "extracted_context": scenario['context'],
            "missing_slots": [],
            "search_results": [],
            "final_products": [],
            "response": None,
            "status": "active",
            "next_agent": "interviewer"
        }
        
        try:
            result = await interviewer_agent(state)
            
            print(f"  Extracted: {result['extracted_context']}")
            print(f"  Missing:   {result['missing_slots']}")
            print(f"  Question:  {result.get('response')}")
            print(f"  Next Agent: {result['next_agent']}")
            print("-" * 30)
            
        except Exception as e:
            print(f"  ❌ Error: {e}")
            print("-" * 30)

if __name__ == "__main__":
    asyncio.run(test_interviewer())
