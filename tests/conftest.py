import pytest
import asyncio
import uuid
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.agents.state import AgentState

settings = get_settings()

# Use the actual database for tests, or a test database if configured
# For now, we'll use the one from settings
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def base_state() -> AgentState:
    return {
        "session_id": uuid.uuid4(),
        "user_message": "",
        "previous_domain_slug": None,
        "domain_slug": None,
        "extracted_context": {},
        "missing_slots": [],
        "initial_products": [],
        "search_results": [],
        "final_products": [],
        "response": None,
        "status": "active",
        "next_agent": None,
        "optional_slot_hint": None,
        "intent_type": "query",
        "journey_type": None,
        "journey_bundle": None
    }
