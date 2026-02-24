from typing import Any, Dict, List
from pydantic import BaseModel, Field, field_validator

from app.agents.validators import parse_dict, parse_bool
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.agents.state import AgentState
from app.agents.llm import get_bedrock_llm

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
    reasoning: str = Field(default="", description="Brief explanation of the decision")

    @field_validator("is_refinement", mode="before")
    @classmethod
    def parse_is_refinement(cls, v: Any) -> bool:
        return parse_bool(v)

    @field_validator("new_constraints", mode="before")
    @classmethod
    def parse_new_constraints(cls, v: Any) -> Dict[str, Any]:
        return parse_dict(v)


def get_refinement_model():
    """Initialize the Bedrock model for refinement detection."""
    return get_bedrock_llm(structured_output_schema=RefinementResponse)


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
- Price/budget mentions: "cheaper", "under $X", "under ₹X", "more affordable", "budget"
- Format changes: "in powder form", "capsules instead", "liquid version"
- Ingredient filters: "without fish", "vegan option", "no allergens"
- Allergy mentions: "I have a fish allergy", "allergic to dairy"
- Quantity: "show more", "other options", "alternatives"

NEW TOPIC indicators (user wants something different):
- Different health goal: "what about sleep?", "energy instead"
- Different product category: "do you have vitamins?"
- Ending conversation: "thanks", "that's all", "goodbye"
- Completely unrelated: weather, general questions

When extracting new_constraints, use these EXACT key names so downstream filters work:
- "allergies": list of allergy strings, e.g. ["fish", "dairy"]
- "dietary_preference": string, e.g. "vegan", "vegetarian"
- "budget_max": number (the numeric value only, strip any currency symbol), e.g. 1000 for "under ₹1000" or 30 for "under $30"
- "format_preference": string, e.g. "capsule", "powder", "liquid"
"""

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
        # Clear previous results and graph state so the new consultation
        # starts fresh (avoids stale questions_asked counter, filled_attributes, etc.)
        new_state["search_results"] = []
        new_state["final_products"] = []
        updated_context = {**extracted_context}
        updated_context.pop("graph_state", None)
        updated_context.pop("candidate_problem", None)
        new_state["extracted_context"] = updated_context

    return new_state
