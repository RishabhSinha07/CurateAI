from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.agents.state import AgentState

settings = get_settings()

class InterviewerResponse(BaseModel):
    """Structured response from the Interviewer agent."""
    extracted_values: Dict[str, Any] = Field(
        description="Dictionary mapping slot names to extracted values from the user's message"
    )
    missing_slots: List[str] = Field(
        description="List of required slot names that are still missing after extraction"
    )
    question: Optional[str] = Field(
        default=None,
        description="A helpful follow-up question if slots are missing, null if all filled"
    )
    reasoning: str = Field(description="Brief explanation of extraction logic")

def _format_optional_slots(slots: List[str]) -> str:
    """Convert slot names into user-friendly hints."""
    friendly_names = {
        "dietary_preference": "dietary preferences (vegan, vegetarian, etc.)",
        "budget": "your budget range",
        "flavor_preference": "flavor preferences",
        "age_group": "your age group",
    }

    formatted = [friendly_names.get(slot, slot.replace("_", " ")) for slot in slots]

    if len(formatted) == 1:
        return formatted[0]
    elif len(formatted) == 2:
        return f"{formatted[0]} or {formatted[1]}"
    else:
        return ", ".join(formatted[:-1]) + f", or {formatted[-1]}"

def get_interviewer_model():
    """Initialize the Bedrock model for interviewing."""
    llm = ChatBedrock(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        model_kwargs={"temperature": 0},
    )
    return llm.with_structured_output(InterviewerResponse)

async def interviewer_agent(state: AgentState) -> AgentState:
    """
    Manages the consultation phase: extracts information and asks clarifying questions.
    """
    domain_config = state.get("domain_config") or {}
    required_slots = domain_config.get("required_slots", [])
    optional_slots = domain_config.get("optional_slots", [])
    extracted_context = state.get("extracted_context", {})
    previous_response = state.get("response")  # The last question we asked

    # Identify what we still need to know
    already_filled = set(extracted_context.keys())
    missing_before = [slot for slot in required_slots if slot not in already_filled]

    if not missing_before and state["status"] != "awaiting_slot":
        # If nothing missing and we weren't specifically waiting, move to search
        new_state = state.copy()
        new_state["next_agent"] = "search"
        return new_state

    # Build context about previous question for better slot mapping
    previous_question_context = ""
    if previous_response and state.get("status") == "awaiting_slot":
        previous_question_context = f"""
Previous Question Asked: "{previous_response}"
The user's message is likely answering this question. Map their response to the appropriate slot.
"""

    system_message = """You are a wellness consultant gathering information to recommend products.
Extract slot values from the user's message and identify what's still missing.

IMPORTANT: When the user gives a short answer (like "capsule", "yes", "powder"), it's likely answering
the previous question. Map it to the correct slot based on context."""

    user_message = f"""Domain: {state.get('domain_slug')}
Required Slots: {required_slots}
Already Filled: {extracted_context}
Slots Still Needed: {missing_before}
{previous_question_context}
User's Message: "{state['user_message']}"

Instructions:
1. Extract any slot values from the user's message
2. For short answers, use the previous question context to determine which slot it fills
3. List slots that are still missing after this extraction
4. If slots are missing, ask ONE clear question for the most important missing slot
5. Common slot mappings:
   - collagen_preference: powder, capsule, liquid, gummies
   - skin_concern: acne, wrinkles, dryness, dark spots, aging, breakouts
   - health_goal: sleep, energy, immunity, digestion, stress, weight
   - format: melts, capsules, powder, effervescent"""

    model = get_interviewer_model()
    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=user_message)
    ]
    result: InterviewerResponse = await model.ainvoke(messages)
    
    # Update state
    new_state = state.copy()

    # Update context with newly extracted values
    new_state["extracted_context"] = {**extracted_context, **result.extracted_values}
    new_state["missing_slots"] = result.missing_slots

    if result.missing_slots:
        new_state["response"] = result.question
        new_state["status"] = "awaiting_slot"
        new_state["next_agent"] = None # End turn to wait for user input
    else:
        # All required slots filled - check if we should suggest optional slots
        unfilled_optional = [
            slot for slot in optional_slots
            if slot not in new_state["extracted_context"]
        ]

        if unfilled_optional:
            # Format optional slot names in a user-friendly way
            optional_hints = _format_optional_slots(unfilled_optional)
            # Store hint to be included by safety agent in final response
            new_state["optional_slot_hint"] = (
                f"You can also share {optional_hints} for more personalized recommendations."
            )
        else:
            new_state["optional_slot_hint"] = None

        new_state["response"] = None
        new_state["status"] = "collecting_info"
        new_state["next_agent"] = "search"

    return new_state
