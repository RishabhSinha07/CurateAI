from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.agents.state import AgentState

settings = get_settings()

class InterviewerResponse(BaseModel):
    """Structured response from the Interviewer agent."""
    extracted_values: Dict[str, Any] = Field(description="Dictionary of information extracted from the user's message")
    missing_slots: List[str] = Field(description="List of required slots that are still missing")
    question: Optional[str] = Field(description="A helpful question to ask the user if slots are missing")
    reasoning: str = Field(description="Brief explanation of extraction and next steps")

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
    extracted_context = state.get("extracted_context", {})
    
    # Identify what we still need to know
    already_filled = set(extracted_context.keys())
    missing_before = [slot for slot in required_slots if slot not in already_filled]
    
    if not missing_before and state["status"] != "awaiting_slot":
        # If nothing missing and we weren't specifically waiting, move to search
        new_state = state.copy()
        new_state["next_agent"] = "search"
        return new_state

    system_prompt = f"""You are a specialist health and wellness consultant for CurateAI. Your goal is to gather specific information (slots) from the user to provide a safe and accurate recommendation.

Domain Context: {state.get('domain_slug')}
Required Information (Slots): {required_slots}
Previously Extracted Information: {extracted_context}

User's Latest Message: "{state['user_message']}"

Your Tasks:
1. EXTRACT: Analyze the user's latest message for any values matching the required slots.
2. VALIDATE: Ensure the extracted values are meaningful for the specific slots.
3. IDENTIFY: Determine which required slots are still missing after this message.
4. ASK: If slots are missing, generate ONE empathetic and professional question to ask the user for the missing information. Do not ask for everything at once if there are many missing; prioritize the most important one.

Guidelines:
- If all required slots are filled, set `missing_slots` to an empty list and `question` to null.
- Maintain a professional, consultative tone.
- Do not repeat questions the user has already answered.
"""

    model = get_interviewer_model()
    result: InterviewerResponse = await model.ainvoke(system_prompt)
    
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
        new_state["status"] = "collecting_info"
        new_state["next_agent"] = "search"
        new_state["response"] = None

    return new_state
