import asyncio
import uuid
from app.db.session import async_session_factory
from app.agents.graph import get_consultation_graph, create_initial_state


async def test_full_graph():
    """Test the complete consultation graph with a multi-turn conversation."""

    print("🚀 Testing Full Consultation Graph...\n")

    graph = get_consultation_graph()

    # Simulate a multi-turn conversation
    conversation = [
        {
            "turn": 1,
            "message": "I need something for better sleep",
            "expected_status": ["collecting_info", "awaiting_slot"],
            "context": {},
            "status": "active",
        },
        {
            "turn": 2,
            "message": "I prefer melts, and my budget is around $30",
            "expected_status": ["searching", "ranked", "completed"],
            "context": {},  # Will be updated from previous turn
            "status": "awaiting_slot",
        },
    ]

    async with async_session_factory() as session:
        session_id = uuid.uuid4()
        accumulated_context = {}
        current_status = "active"
        domain_id = None
        domain_slug = None
        domain_config = None

        for turn in conversation:
            print(f"--- Turn {turn['turn']} ---")
            print(f"User: {turn['message']}")

            # Create state for this turn
            state = create_initial_state(
                session_id=session_id,
                user_message=turn["message"],
                existing_context=accumulated_context,
                existing_status=current_status,
                domain_id=domain_id,
                domain_slug=domain_slug,
                domain_config=domain_config,
            )

            try:
                result = await graph.run(state, session)

                print(f"Status: {result['status']}")
                print(f"Domain: {result.get('domain_slug')}")
                print(f"Context: {result.get('extracted_context')}")

                if result.get("response"):
                    preview = result["response"][:200]
                    print(f"Response: {preview}...")

                if result.get("final_products"):
                    print(f"Products recommended: {len(result['final_products'])}")
                    for p in result["final_products"][:2]:
                        print(f"  - {p['name']}")

                # Update for next turn
                accumulated_context = result.get("extracted_context", {})
                current_status = result.get("status", "active")
                domain_id = result.get("domain_id")
                domain_slug = result.get("domain_slug")
                domain_config = result.get("domain_config")

                print()

            except Exception as e:
                print(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()
                break


async def test_out_of_scope():
    """Test handling of out-of-scope requests."""

    print("\n🚀 Testing Out-of-Scope Handling...\n")

    graph = get_consultation_graph()

    async with async_session_factory() as session:
        state = create_initial_state(
            session_id=uuid.uuid4(),
            user_message="What's the weather like today?",
            existing_context={},
            existing_status="active",
        )

        try:
            result = await graph.run(state, session)

            print(f"Status: {result['status']}")
            print(f"Response: {result.get('response')}")
            print(f"Domain: {result.get('domain_slug')}")

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()


async def run_all_tests():
    """Run all graph tests in a single async context."""
    await test_full_graph()
    await test_out_of_scope()


if __name__ == "__main__":
    asyncio.run(run_all_tests())
