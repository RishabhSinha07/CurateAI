import pytest
import uuid
from app.agents.graph import get_consultation_graph, create_initial_state
from app.db.session import async_session_factory

@pytest.mark.asyncio
async def test_full_consultation_flow():
    """Test the complete consultation graph with a multi-turn conversation."""
    graph = get_consultation_graph()

    # Simulate a multi-turn conversation
    conversation = [
        {
            "turn": 1,
            "message": "I need something for better sleep",
            "expected_status_any": ["collecting_info", "awaiting_slot"],
        },
        {
            "turn": 2,
            "message": "I prefer melts, and my budget is around 3000",
            "expected_status_any": ["searching", "ranked", "completed"],
        },
    ]

    async with async_session_factory() as session:
        session_id = uuid.uuid4()
        accumulated_context = {}
        current_status = "active"
        domain_slug = None

        for turn in conversation:
            # Create state for this turn
            state = create_initial_state(
                session_id=session_id,
                user_message=turn["message"],
                existing_context=accumulated_context,
                existing_status=current_status,
                domain_slug=domain_slug,
            )

            result = await graph.run(state, session)

            assert result["status"] in turn["expected_status_any"]
            if turn["turn"] == 1:
                assert result["domain_slug"] in ["wellness", "sleep"]
            
            # Update for next turn
            accumulated_context = result.get("extracted_context", {})
            current_status = result.get("status", "active")
            domain_slug = result.get("domain_slug")

@pytest.mark.asyncio
async def test_out_of_scope_flow():
    """Test handling of out-of-scope requests in the full graph."""
    graph = get_consultation_graph()

    async with async_session_factory() as session:
        state = create_initial_state(
            session_id=uuid.uuid4(),
            user_message="What's the weather like today?",
            existing_context={},
            existing_status="active",
        )

        result = await graph.run(state, session)

        assert result["status"] == "out_of_scope"
        assert result["domain_slug"] == "out_of_scope"
        assert result["response"] is not None
