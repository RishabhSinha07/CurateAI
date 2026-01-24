from typing import Any, Dict, List
from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.agents.state import AgentState

settings = get_settings()


class RefinementResponse(BaseModel):
    """Structured response from the Refinement detection agent."""
    is_refinement: bool = Field(
        description="True if user wants to refine/filter existing results, False if new topic"
    )
    new_constraints: Dict[str, Any] = Field(
        default_factory=dict,
        description="New constraints to add (e.g., budget, format preference)"
    )
    reasoning: str = Field(description="Brief explanation of the decision")


def get_refinement_model():
    """Initialize the Bedrock model for refinement detection."""
    llm = ChatBedrock(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        model_kwargs={"temperature": 0},
    )
    return llm.with_structured_output(RefinementResponse)


async def refinement_agent(state: AgentState) -> AgentState:
    """
    Detects if user wants to refine previous results or start a new topic.

    Refinement examples:
    - "show me cheaper options"
    - "under $30"
    - "do you have powder form?"
    - "anything without fish?"

    New topic examples:
    - "what about sleep supplements?"
    - "I need energy instead"
    - "thanks, that's all"
    """
    user_message = state.get("user_message", "")
    extracted_context = state.get("extracted_context", {})
    domain_slug = state.get("domain_slug")

    system_message = """You are analyzing if a user wants to refine their product search or start a new topic.

REFINEMENT indicators (user wants to filter/adjust current results):
- Price/budget mentions: "cheaper", "under $X", "more affordable", "budget"
- Format changes: "in powder form", "capsules instead", "liquid version"
- Ingredient filters: "without fish", "vegan option", "no allergens"
- Quantity: "show more", "other options", "alternatives"

NEW TOPIC indicators (user wants something different):
- Different health goal: "what about sleep?", "energy instead"
- Different product category: "do you have vitamins?"
- Ending conversation: "thanks", "that's all", "goodbye"
- Completely unrelated: weather, general questions"""

    user_prompt = f"""Current domain: {domain_slug}
Current preferences: {extracted_context}

User's message: "{user_message}"

Is this a refinement of the current search or a new topic?
If refinement, extract the new constraints (budget, format, ingredients, etc.)."""

    model = get_refinement_model()
    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=user_prompt)
    ]
    result: RefinementResponse = await model.ainvoke(messages)

    new_state = state.copy()

    if result.is_refinement:
        # Merge new constraints into existing context
        new_state["extracted_context"] = {**extracted_context, **result.new_constraints}
        new_state["status"] = "refining"
        new_state["next_agent"] = "search"
    else:
        # New topic - go through router
        new_state["status"] = "active"
        new_state["next_agent"] = "router"
        # Clear previous results but keep session
        new_state["search_results"] = []
        new_state["final_products"] = []

    return new_state
