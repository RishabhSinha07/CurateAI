from typing import TypedDict, Annotated
import uuid

class AgentState(TypedDict):
    # Session metadata
    session_id: uuid.UUID
    user_message: str
    
    # Domain information
    domain_id: uuid.UUID | None
    domain_slug: str | None
    domain_config: dict | None
    
    # Intelligence state
    extracted_context: dict
    missing_slots: list[str]
    
    # Search & Results
    search_results: list[dict]
    final_products: list[dict]
    
    # Orchestration
    response: str | None
    status: str  # active, collecting_info, awaiting_slot, completed, out_of_scope
    next_agent: str | None
