from typing import List, Optional
from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock

from app.config import get_settings
from app.agents.state import AgentState
from app.agents.response_formatter import (
    format_intro_with_constraints,
    format_disclaimers,
    format_no_results_message,
    format_out_of_scope_message,
)

settings = get_settings()


class SafetyResponse(BaseModel):
    """Structured response from the Safety agent."""
    response: str = Field(default="", description="The final user-facing response with recommendations")
    disclaimers: List[str] = Field(default_factory=list, description="Any safety disclaimers that should be appended")
    contains_medical_claims: bool = Field(default=False, description="Whether the response contains medical claims that need disclaimers")
    is_safe: bool = Field(default=True, description="Whether the response is safe to send")


def get_safety_model():
    """Initialize the Bedrock model for safety checking."""
    llm = ChatBedrock(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        model_kwargs={"temperature": 0.3},  # Slightly higher for natural responses
    )
    return llm.with_structured_output(SafetyResponse)


async def safety_agent(state: AgentState) -> AgentState:
    """
    Generates the final response with appropriate safety disclaimers.

    This agent:
    1. Generates a natural recommendation response
    2. Checks for medical claims
    3. Appends domain-specific disclaimers
    4. Includes information about safety constraints that were applied
    5. Handles out-of-scope requests gracefully
    """
    status = state.get("status", "")
    domain_config = state.get("domain_config") or {}
    final_products = state.get("final_products", [])
    extracted_context = state.get("extracted_context", {})
    safety_disclaimers = domain_config.get("safety_disclaimers", [])

    # Extract applied safety constraints from context
    applied_constraints = []
    graph_state = extracted_context.get("graph_state", {})
    filled_attrs = graph_state.get("filled_attributes", {})

    # Check for medical constraints
    if "medical_constraints" in filled_attrs:
        value = filled_attrs["medical_constraints"].get("value", "")
        if isinstance(value, list):
            for constraint in value:
                if not isinstance(constraint, str):
                    continue
                constraint_lower = constraint.lower()
                if constraint_lower not in ["none", "none of the above"]:
                    applied_constraints.append(f"Medical: {constraint}")
        elif isinstance(value, str) and value:
            value_lower = value.lower()
            if "none" not in value_lower:
                applied_constraints.append(f"Medical: {value}")

    # Check for allergy constraints
    if "allergies" in filled_attrs:
        value = filled_attrs["allergies"].get("value", "")
        if isinstance(value, list):
            for allergy in value:
                if not isinstance(allergy, str):
                    continue
                allergy_lower = allergy.lower()
                if "no allerg" not in allergy_lower and allergy_lower != "none":
                    applied_constraints.append(f"Allergy: {allergy.replace(' allergy', '')}")
        elif isinstance(value, str) and value:
            value_lower = value.lower()
            if "no allerg" not in value_lower:
                applied_constraints.append(f"Allergy: {value.replace(' allergy', '')}")

    # Check for dietary constraints
    if "diet" in filled_attrs:
        value = filled_attrs["diet"].get("value", "")
        if isinstance(value, str) and value:
            value_lower = value.lower()
            if value_lower in ["vegan", "vegetarian"]:
                applied_constraints.append(f"Diet: {value.capitalize()}")

    # Handle out-of-scope requests
    if status == "out_of_scope":
        new_state = state.copy()
        new_state["response"] = format_out_of_scope_message()
        new_state["status"] = "completed"
        new_state["next_agent"] = None
        return new_state

    # Handle no results
    if not final_products:
        new_state = state.copy()
        has_constraints = bool(applied_constraints)
        new_state["response"] = format_no_results_message(extracted_context, has_constraints)
        new_state["status"] = "completed"
        new_state["next_agent"] = None
        return new_state

    # Check if this is a journey bundle response
    journey_bundle = state.get("journey_bundle")
    intent_type = state.get("intent_type")

    if intent_type == "journey" and journey_bundle:
        # Product cards are rendered by the frontend, so the text response
        # only needs the journey intro — no product listing.
        journey_response = f"# {journey_bundle['journey_name']}\n\n{journey_bundle['journey_description']}"

        # Add disclaimers
        if safety_disclaimers:
            journey_response += "\n\n" + format_disclaimers(safety_disclaimers)
        else:
            # Default disclaimer
            default_disclaimer = [
                "These statements have not been evaluated by the FDA. These products are not intended to diagnose, treat, cure, or prevent any disease. Please consult with a healthcare professional before starting any new supplement regimen."
            ]
            journey_response += "\n\n" + format_disclaimers(default_disclaimer)

        new_state = state.copy()
        new_state["response"] = journey_response
        new_state["status"] = "completed"
        new_state["next_agent"] = None
        return new_state

    # Regular query flow — product cards are rendered by the frontend,
    # so we only build the intro text here.
    intro = format_intro_with_constraints(applied_constraints)

    # Build constraint information for the LLM prompt
    constraint_info = ""
    if applied_constraints:
        constraint_list = "\n".join(f"  - {c}" for c in applied_constraints)
        constraint_info = f"""
Safety Constraints Applied:
{constraint_list}

IMPORTANT: The intro already mentions these constraints. DO NOT repeat them in your response.
"""

    system_prompt = f"""You are a wellness consultant for CurateAI. Generate a brief, well-formatted intro for product recommendations using **Markdown**.

User's Context/Preferences:
{extracted_context}
{constraint_info}

The product cards are displayed separately by the UI. Your job is to write a SHORT intro (3-5 sentences) that:
- Introduces the recommendations naturally
- DOES NOT repeat constraint information (it's already in the intro)
- DOES NOT greet the user ("Hey there!", "Hello!")
- DOES NOT use acknowledgment phrases ("I heard you're looking for...")
- DOES NOT list individual product names (the product cards handle that)
- Highlights what makes these products good choices for their needs
- Summarises the key benefits the user can expect

**Formatting rules — you MUST use Markdown:**
- Use **bold** to emphasise key benefits or ingredients
- Use short paragraphs (2-3 sentences each) separated by blank lines
- You may use a short bullet list (2-3 items max) to highlight key benefits
- Keep the overall response concise — no more than 5 sentences total

Domain-Specific Safety Guidelines:
{safety_disclaimers}

Your Tasks:
1. INTRO: Write a Markdown-formatted intro as described above
2. SAFETY CHECK: Note if you make any medical claims
3. DISCLAIMERS: List any needed disclaimers based on domain guidelines

Guidelines:
- Use phrases like "may support", "designed to help", "formulated for"
- Never claim products treat, cure, or prevent any disease
"""

    model = get_safety_model()
    result: SafetyResponse = await model.ainvoke(system_prompt)

    # Build final response with proper sections
    # NOTE: Product cards are rendered by the frontend from the structured
    # `products` array, so we only include the intro text here — no markdown
    # product listing to avoid duplication.
    response_parts = []

    # Add intro with constraints if present
    if intro:
        response_parts.append(intro.strip())

    # Add LLM-generated intro paragraph
    if result.response:
        response_parts.append(result.response.strip())

    final_response = "\n\n".join(response_parts)

    # Add optional slot hint at the top if present
    optional_slot_hint = state.get("optional_slot_hint")
    if optional_slot_hint:
        final_response = f"{optional_slot_hint}\n\n{final_response}"

    # Append disclaimers if needed
    if result.disclaimers:
        final_response += "\n\n" + format_disclaimers(result.disclaimers)
    elif result.contains_medical_claims:
        # Default disclaimer for health products
        default_disclaimer = [
            "These statements have not been evaluated by the FDA. These products are not intended to diagnose, treat, cure, or prevent any disease. Please consult with a healthcare professional before starting any new supplement regimen."
        ]
        final_response += "\n\n" + format_disclaimers(default_disclaimer)

    # Update state
    new_state = state.copy()
    new_state["response"] = final_response
    new_state["status"] = "completed"
    new_state["next_agent"] = None

    return new_state
