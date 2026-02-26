from typing import Any, Dict
from pydantic import BaseModel, Field, field_validator

from app.agents.validators import parse_dict, parse_bool
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.agents.state import AgentState
from app.agents.llm import get_bedrock_llm

settings = get_settings()


class RefinementResponse(BaseModel):
    """Structured response from the Refinement detection agent."""
    intent: str = Field(
        description=(
            "One of: "
            "'refinement' if user wants to filter/adjust current results, "
            "'re_personalize' if user wants to restart the personalization interview for the same domain, "
            "'ingredient_info' if user is asking an educational question about an ingredient or supplement, "
            "'new_topic' if user wants something completely different"
        )
    )
    new_constraints: Dict[str, Any] = Field(
        default_factory=dict,
        description="New constraints to add (e.g., budget, format preference). Only for refinement intent."
    )
    reasoning: str = Field(default="", description="Brief explanation of the decision")

    # Keep is_refinement as a computed property for backward compatibility
    @property
    def is_refinement(self) -> bool:
        return self.intent == "refinement"

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

    system_message = """You are analyzing what a user wants to do after seeing product recommendations.

Classify into ONE of three intents:

INGREDIENT_INFO — user is asking an educational question about an ingredient or supplement:
- Key signals: "how does X work", "why should I use X", "what does X do", "tell me about X", "benefits of X", "when should I take X", "how to take X", "is X safe", "side effects of X", "explain X"
- Pronouns referring to a shown product/ingredient: "when should I take this?", "how does it work?", "is it safe?"
- These users want to learn, not buy — route to ingredient_info, do NOT search for products.

RE_PERSONALIZE — user wants to restart the personalization interview for the same domain:
- Keywords: "personalise", "personalize", "customise", "customize", "personalise for me", "personalize for me", "make it personal", "tailor this", "based on my needs", "for my needs"
- These users want the system to ask them questions (age, goals, preferences) to find better-matched products.

REFINEMENT — user wants to filter/adjust the current results without re-interviewing:
- Price/budget: "cheaper", "under ₹X", "more affordable", "budget"
- Format: "in powder form", "capsules instead", "liquid version"
- Ingredient filters: "without fish", "vegan option", "no allergens"
- Allergy mentions: "I have a fish allergy", "allergic to dairy"
- Quantity: "show more", "other options", "alternatives"

NEW_TOPIC — user wants something completely different:
- Different health goal: "what about sleep?", "energy instead"
- Ending conversation: "thanks", "that's all", "goodbye"
- Completely unrelated: weather, general questions

When extracting new_constraints (only for REFINEMENT), use these EXACT key names:
- "allergies": list of allergy strings, e.g. ["fish", "dairy"]
- "dietary_preference": string, e.g. "vegan", "vegetarian"
- "budget_max": number (strip currency symbol), e.g. 1000 for "under ₹1000"
- "format_preference": string, e.g. "capsule", "powder", "liquid"

Return intent as one of: "ingredient_info", "refinement", "re_personalize", "new_topic"
"""

    user_prompt = f"""Current domain: {domain_slug}
Current preferences: {extracted_context}

User's message: "{user_message}"

Classify the intent and extract constraints if applicable."""

    model = get_refinement_model()
    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=user_prompt)
    ]
    result: RefinementResponse = await model.ainvoke(messages)

    new_state = state.copy()

    if result.intent == "ingredient_info":
        # Educational question — route to ingredient_info, preserve all state
        new_state["next_agent"] = "ingredient_info"
    elif result.intent == "refinement":
        # Merge new constraints into existing context
        new_state["extracted_context"] = {**extracted_context, **result.new_constraints}
        new_state["status"] = "refining"
        new_state["next_agent"] = "search"
    elif result.intent == "re_personalize":
        # User wants to restart the interview for the same domain.
        # Clear graph state so the interviewer starts a fresh slot-filling pass,
        # but keep domain_slug so we don't re-route.
        updated_context = {**extracted_context}
        updated_context.pop("graph_state", None)
        updated_context.pop("candidate_problem", None)
        new_state["extracted_context"] = updated_context
        new_state["search_results"] = []
        new_state["final_products"] = []
        new_state["status"] = "collecting_info"
        new_state["next_agent"] = "interviewer"
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
