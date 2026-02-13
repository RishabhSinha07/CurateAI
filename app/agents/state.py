from typing import TypedDict, Annotated
import uuid

class AgentState(TypedDict):
    # Session metadata
    session_id: uuid.UUID
    user_message: str
    
    # Domain information (now graph-based, no DB FK needed)
    previous_domain_slug: str | None  # Domain before this turn (for change detection)
    domain_slug: str | None
    
    # Intelligence state
    extracted_context: dict
    missing_slots: list[str]
    
    # Search & Results
    initial_products: list[dict]  # First-pass domain products shown before interview
    search_results: list[dict]
    final_products: list[dict]
    
    # Orchestration
    response: str | None
    suggested_replies: list[str]  # Quick-reply options surfaced by the interviewer
    status: str  # active, collecting_info, awaiting_slot, completed, out_of_scope
    next_agent: str | None
    optional_slot_hint: str | None  # Hint about optional slots to show with final response
    
    # Journey-specific fields
    intent_type: str | None  # "query" or "journey"
    journey_type: str | None  # e.g., "beginner_gym", "skincare_routine_start"
    journey_bundle: dict | None  # Journey info with name, description, and products with usage guidance
