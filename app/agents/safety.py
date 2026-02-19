from typing import Any, List, Optional
import logging
from pydantic import BaseModel, Field, field_validator

from app.agents.validators import parse_list, parse_bool

from app.config import get_settings
from app.agents.state import AgentState
from app.agents.llm import get_bedrock_llm
from app.agents.response_formatter import (
    format_intro_with_constraints,
    format_disclaimers,
    format_no_results_message,
)
from app.knowledge.graph_loader import get_knowledge_graph

settings = get_settings()
logger = logging.getLogger(__name__)


class SafetyResponse(BaseModel):
    """Structured response from the Safety agent."""
    response: str = Field(default="", description="The final user-facing response with recommendations")
    disclaimers: List[str] = Field(default_factory=list, description="Any safety disclaimers that should be appended")
    contains_medical_claims: bool = Field(default=False, description="Whether the response contains medical claims that need disclaimers")
    is_safe: bool = Field(default=True, description="Whether the response is safe to send")

    @field_validator("disclaimers", mode="before")
    @classmethod
    def parse_disclaimers(cls, v: Any) -> List[Any]:
        return parse_list(v)

    @field_validator("contains_medical_claims", "is_safe", mode="before")
    @classmethod
    def parse_bools(cls, v: Any) -> bool:
        return parse_bool(v)


def get_safety_model():
    """Initialize the Bedrock model for safety checking."""
    return get_bedrock_llm(
        model_kwargs={"temperature": 0.3},
        structured_output_schema=SafetyResponse,
    )


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

    # --- Gather richer context from the knowledge graph ---
    problem_id = graph_state.get("identified_problem")
    graph_domain = graph_state.get("graph_domain")

    problem_display_name = ""
    problem_description = ""
    treating_ingredients_info = []

    if problem_id and graph_domain:
        try:
            graph = get_knowledge_graph(graph_domain)

            # Problem info
            problem_node = graph.get_node(problem_id)
            if problem_node:
                problem_display_name = problem_node.get("display_name", problem_id)
                problem_description = problem_node.get("description", "")

            # Top treating ingredients
            raw_ingredients = graph.get_treating_ingredients(problem_id, min_efficacy=0.5)
            for ing in raw_ingredients[:5]:
                treating_ingredients_info.append({
                    "name": ing.get("display_name", ing.get("name", "")),
                    "mechanism": ing.get("mechanism", ""),
                    "onset_time": ing.get("onset_time", ""),
                })
        except Exception as e:
            logger.warning(f"Error gathering knowledge graph context for safety agent: {e}")

    # Build user profile summary from filled attributes
    profile_parts = []
    for attr_key, attr_val in filled_attrs.items():
        if attr_key in ("medical_constraints", "allergies"):
            continue  # Already captured in applied_constraints
        value = attr_val.get("value", "")
        display = attr_val.get("display_name", attr_key.replace("_", " ").title())
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        if value:
            profile_parts.append(f"{display}: {value}")
    user_profile_summary = "\n".join(f"- {p}" for p in profile_parts) if profile_parts else "No specific profile details collected."

    # Build treating ingredients block for the prompt
    ingredients_block = ""
    if treating_ingredients_info:
        lines = []
        for ing in treating_ingredients_info:
            parts = [f"- **{ing['name']}**"]
            if ing["mechanism"]:
                parts[0] += f": {ing['mechanism']}"
            if ing["onset_time"]:
                parts[0] += f" (onset: {ing['onset_time']})"
            lines.append(parts[0])
        ingredients_block = "\n".join(lines)
    else:
        ingredients_block = "No specific ingredient data available."

    # Build problem block
    problem_block = ""
    if problem_display_name:
        problem_block = f"{problem_display_name}"
        if problem_description:
            problem_block += f" — {problem_description}"
    else:
        problem_block = "General wellness query"

    # Regular query flow — product cards are rendered by the frontend,
    # so we only build the intro text here.
    intro = format_intro_with_constraints(applied_constraints)

    # Build constraint information for the LLM prompt
    constraint_info = ""
    if applied_constraints:
        constraint_list = "\n".join(f"  - {c}" for c in applied_constraints)
        constraint_info = f"""
Applied Constraints:
{constraint_list}
"""

    system_prompt = f"""You are a wellness consultant for CurateAI. Generate a structured, deeply personalized response using **Markdown**.

The product cards are displayed separately by the UI — do NOT list individual product names.

---

**User Profile:**
{user_profile_summary}

**Problem:**
{problem_block}

**Key Treating Ingredients:**
{ingredients_block}
{constraint_info}
**Safety Guidelines:**
{safety_disclaimers}

---

Write your response following these 4 layers IN ORDER:

## Understanding Your Needs
(Layer 1 — Reflect, 2-3 sentences) Restate the user's situation using their profile and concern. Show you understood their specific circumstances. No greetings, no filler, no acknowledgment phrases ("I heard you're looking for...").

## What's Going On
(Layer 2 — Reframe, 2-3 sentences) Based on the problem description and treating ingredients, explain possible drivers or mechanisms behind the concern. Use hedging language — "may", "often", "could" — never diagnose.

## What Can Help
(Layer 3 — Recommendations)

**Lifestyle Foundations**
- 2-3 practical, non-product suggestions relevant to the problem (sleep, hydration, stress, diet tips)

(Do NOT list product names or specific ingredients — the product cards handle that.)

## Important to Know
(Layer 4 — Safety, 1-3 bullets) Who should be cautious, what to monitor, when to consult a professional. Base this on the domain safety guidelines and any applied constraints.

---

**Formatting rules:**
- Use `##` headings exactly as shown above
- **Bold** key terms and ingredient names
- Bullets for lists
- Short paragraphs (2-3 sentences each)
- Total response: ~150-250 words
- NEVER list product names (product cards are rendered separately)
- NEVER greet the user

**Language guidelines:**
- Use phrases like "may support", "designed to help", "formulated for"
- Never claim products treat, cure, or prevent any disease

Your Tasks:
1. RESPONSE: Write the 4-layer response as described
2. SAFETY CHECK: Note if you make any medical claims
3. DISCLAIMERS: List any needed disclaimers based on domain guidelines
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

    # Add LLM-generated structured response
    if result.response:
        response_parts.append(result.response.strip())

    final_response = "\n\n".join(response_parts)

    # Add optional slot hint at the top if present
    optional_slot_hint = state.get("optional_slot_hint")
    if optional_slot_hint:
        final_response = f"{optional_slot_hint}\n\n{final_response}"

    # Append disclaimers from the LLM if present
    if result.disclaimers:
        final_response += "\n\n" + format_disclaimers(result.disclaimers)
    elif result.contains_medical_claims:
        # Default disclaimer for health products
        default_disclaimer = [
            "These statements have not been evaluated by the FDA. These products are not intended to diagnose, treat, cure, or prevent any disease. Please consult with a healthcare professional before starting any new supplement regimen."
        ]
        final_response += "\n\n" + format_disclaimers(default_disclaimer)

    # Layer 5: Append domain-specific disclaimers programmatically
    if safety_disclaimers:
        final_response += "\n\n" + format_disclaimers(safety_disclaimers)

    # Update state
    new_state = state.copy()
    new_state["response"] = final_response
    new_state["status"] = "completed"
    new_state["next_agent"] = None

    return new_state
