from typing import Any, Dict, List, Optional, Tuple
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

# Domain-specific default disclaimers. Domains not listed here get no default disclaimer.
_DOMAIN_DISCLAIMERS: dict[str, str] = {
    "wellness": (
        "These statements have not been evaluated by the FDA. These products "
        "are not intended to diagnose, treat, cure, or prevent any disease. "
        "Please consult with a healthcare professional before starting any "
        "new supplement regimen."
    ),
    "rural-equipment": (
        "Always follow the manufacturer's safety instructions and wear "
        "appropriate protective equipment when operating machinery. "
        "Specifications are provided by the manufacturer and may vary."
    ),
}


def _get_default_disclaimer(domain_slug: str | None) -> list[str]:
    """Return domain-appropriate default disclaimer, or empty list if none applies."""
    if not domain_slug:
        # Backward compat: default to wellness disclaimer when domain is unknown
        return [_DOMAIN_DISCLAIMERS["wellness"]]
    # Check exact match first
    disclaimer = _DOMAIN_DISCLAIMERS.get(domain_slug)
    if not disclaimer:
        # All non-rural domains are wellness-related
        if domain_slug != "rural-equipment":
            disclaimer = _DOMAIN_DISCLAIMERS.get("wellness")
    return [disclaimer] if disclaimer else []


# ---------------------------------------------------------------------------
# Domain-aware response configuration
# ---------------------------------------------------------------------------
# Each entry controls the persona fallback, response layer wording, language
# guidelines, and the suggested-reply filter chips shown after results.
# Domains not listed here fall through to "_default" (wellness-style).

_DOMAIN_RESPONSE_CONFIG: Dict[str, Dict[str, Any]] = {
    "rural-equipment": {
        "fallback_problem_label": "General equipment query",
        "lifestyle_heading": "Practical Considerations",
        "lifestyle_guidance": (
            "2-3 practical, non-product suggestions relevant to the task "
            "(safety precautions, maintenance tips, workspace or terrain setup)"
        ),
        "language_guidelines": (
            '- Use phrases like "well-suited for", "designed to handle", "built for"\n'
            "- Never overstate equipment capabilities beyond manufacturer specifications"
        ),
        # (attr_key, exclude_value_if_present, chip_label)
        "refinement_filters": [
            ("power_type", None, "Electric option"),
            ("category", None, "Show accessories"),
        ],
    },
    "_default": {
        "fallback_problem_label": "General wellness query",
        "lifestyle_heading": "Lifestyle Foundations",
        "lifestyle_guidance": (
            "2-3 practical, non-product suggestions relevant to the problem "
            "(sleep, hydration, stress, diet tips)"
        ),
        "language_guidelines": (
            '- Use phrases like "may support", "designed to help", "formulated for"\n'
            "- Never claim products treat, cure, or prevent any disease"
        ),
        "refinement_filters": [
            ("dietary_preference", "vegan", "Vegan options"),
            ("format_preference", None, "Capsule form"),
        ],
    },
}


def _get_domain_response_config(domain_slug: str | None) -> Dict[str, Any]:
    """Return the response config for *domain_slug*, falling back to _default."""
    if domain_slug and domain_slug in _DOMAIN_RESPONSE_CONFIG:
        return _DOMAIN_RESPONSE_CONFIG[domain_slug]
    return _DOMAIN_RESPONSE_CONFIG["_default"]


def _get_persona(domain_slug: str | None) -> str:
    """Return the persona string from the knowledge graph, with fallback."""
    if domain_slug:
        try:
            graph = get_knowledge_graph(domain_slug)
            if graph.metadata and graph.metadata.persona:
                return graph.metadata.persona
        except Exception:
            pass
    return "You are a wellness consultant for CurateAI."


def _build_filter_suggestions(
    config: Dict[str, Any],
    extracted_context: Dict[str, Any],
    filled_attrs: Dict[str, Any],
    new_constraints: Dict[str, Any] | None = None,
) -> List[str]:
    """Build domain-appropriate filter suggestion chips."""
    suggestions: List[str] = []
    check_source = new_constraints if new_constraints is not None else extracted_context
    for attr_key, exclude_value, label in config["refinement_filters"]:
        if exclude_value:
            # Check if user already has this value
            current_val = str(check_source.get(attr_key) or "").lower()
            if new_constraints is None:
                # Also check filled_attrs for the main flow
                current_val += " " + " ".join(
                    str(v.get("value", "")).lower()
                    for v in filled_attrs.values()
                    if isinstance(v, dict)
                )
            if exclude_value not in current_val:
                suggestions.append(label)
        else:
            if attr_key not in check_source:
                suggestions.append(label)
    return suggestions


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
    domain_slug = state.get("domain_slug")
    domain_config = state.get("domain_config") or {}
    final_products = state.get("final_products", [])
    user_message = state.get("user_message", "")
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

    # --- Refinement short-circuit ---
    # When the user filtered existing results (cheaper, vegan, capsule form etc.),
    # the Refinement agent sets _is_refinement_pass=True in extracted_context.
    # (We can't rely on status="refining" because Search/Reranker overwrite it.)
    # Skip the full LLM consultation and return a brief contextual message so
    # the same "Understanding Your Needs" wall of text doesn't repeat on every filter.
    if extracted_context.get("_is_refinement_pass"):
        new_constraints = {
            k: v for k, v in extracted_context.items()
            if k in ("budget_max", "dietary_preference", "format_preference", "allergies")
        }

        filter_labels = []
        if "budget_max" in new_constraints:
            # Detect currency symbol from products
            _currency_symbols = {"INR": "₹", "USD": "$", "GBP": "£", "EUR": "€"}
            _currency = next(
                (p.get("currency", "USD").upper() for p in final_products if p.get("currency")),
                "USD"
            )
            _symbol = _currency_symbols.get(_currency, "$")
            filter_labels.append(f"under {_symbol}{int(new_constraints['budget_max'])}")
        if "dietary_preference" in new_constraints:
            filter_labels.append(new_constraints["dietary_preference"].lower())
        if "format_preference" in new_constraints:
            filter_labels.append(f"{new_constraints['format_preference'].lower()} form")
        if "allergies" in new_constraints:
            allergies = new_constraints["allergies"]
            if isinstance(allergies, list):
                filter_labels.append(f"no {', '.join(allergies)}")

        if filter_labels:
            filter_desc = " · ".join(filter_labels)
            refinement_response = f"Here are your filtered results ({filter_desc})."
        else:
            refinement_response = "Here are your updated results."

        new_state = state.copy()
        # Clear both flags so they don't persist into future turns
        cleared_context = {
            k: v for k, v in extracted_context.items()
            if k not in ("_is_refinement_pass", "_resume_interview")
        }
        new_state["extracted_context"] = cleared_context

        # If filtering happened mid-interview (initial products phase), restore
        # the awaiting_slot status and re-surface the pending question so the
        # interview continues after showing the filtered products.
        resume_interview = extracted_context.get("_resume_interview", False)
        if resume_interview:
            pending_q = cleared_context.get("pending_slot_question")
            if pending_q:
                refinement_response += f"\n\n{pending_q}"
            new_state["status"] = "awaiting_slot"
        else:
            new_state["status"] = "completed"

        new_state["response"] = refinement_response
        new_state["next_agent"] = None
        # Rebuild filter suggestions excluding already-applied filters
        filter_suggestions = []
        if "budget_max" not in new_constraints:
            _currency = next(
                (p.get("currency", "USD").upper() for p in final_products if p.get("currency")),
                "USD"
            )
            _symbol = {"INR": "₹", "USD": "$", "GBP": "£", "EUR": "€"}.get(_currency, "$")
            _threshold = {"INR": 1000, "USD": 50, "GBP": 40, "EUR": 45}.get(_currency, 50)
            filter_suggestions.append(f"Under {_symbol}{_threshold}")
        # Mid-interview: don't suggest filters — suggested_replies should be
        # the slot question's answer options, which the Interviewer will provide
        # on the next turn. Leave empty here.
        if not resume_interview:
            refine_config = _get_domain_response_config(domain_slug)
            filter_suggestions.extend(
                _build_filter_suggestions(refine_config, extracted_context, {}, new_constraints)
            )
        new_state["suggested_replies"] = filter_suggestions
        return new_state

    # Check if this is a journey bundle response
    journey_bundle = state.get("journey_bundle")
    intent_type = state.get("intent_type")

    # Direct product intent — brief LLM-generated response with benefits
    if intent_type == "direct_product":
        direct_search_term = extracted_context.get("direct_search_term", "your search")

        # Gather product summaries for context
        product_summaries = []
        for p in final_products[:5]:
            summary = p.get("name", "")
            if p.get("brand"):
                summary += f" by {p['brand']}"
            if p.get("match_reasons"):
                reasons = p["match_reasons"] if isinstance(p["match_reasons"], list) else [p["match_reasons"]]
                summary += f" — {'; '.join(reasons)}"
            product_summaries.append(summary)
        products_block = "\n".join(f"- {s}" for s in product_summaries) if product_summaries else "No product details available."

        dp_persona = _get_persona(domain_slug)
        dp_config = _get_domain_response_config(domain_slug)

        direct_prompt = f"""{dp_persona} The user searched directly for **{direct_search_term}**.

Here are the top matching products (product cards are shown separately by the UI — do NOT list product names):
{products_block}

Write a short, conversational response (60-100 words) that:
1. Acknowledges what they searched for
2. Briefly explains why **{direct_search_term}** is beneficial — key mechanisms or expected benefits (1-2 sentences)
3. A practical tip on what to look for or how to get the most out of it (1 sentence)

**Rules:**
- Do NOT list or name individual products — the UI handles that
- Do NOT greet the user
- Use **bold** for key terms
- Keep it warm but concise

**Language guidelines:**
{dp_config["language_guidelines"]}

**IMPORTANT: Respond in the same language as the user's message below.**
User's message: "{user_message}"

Your Tasks:
1. RESPONSE: Write the brief response
2. SAFETY CHECK: Note if you make any medical claims
3. DISCLAIMERS: List any needed disclaimers
"""

        try:
            model = get_safety_model()
            result: SafetyResponse = await model.ainvoke(direct_prompt)
            response = result.response.strip() if result.response else f"Here are products matching **{direct_search_term}**."

            # Append disclaimers from the LLM if present
            if result.disclaimers:
                response += "\n\n" + format_disclaimers(result.disclaimers)
            elif result.contains_medical_claims:
                default_disclaimer = _get_default_disclaimer(domain_slug)
                if default_disclaimer:
                    response += "\n\n" + format_disclaimers(default_disclaimer)
        except Exception as e:
            logger.warning(f"Direct product LLM call failed, using fallback: {e}")
            response = f"Here are products matching **{direct_search_term}**."

        # Append domain-appropriate default disclaimer
        default_disclaimer = _get_default_disclaimer(domain_slug)
        if default_disclaimer:
            response += "\n\n" + format_disclaimers(default_disclaimer)

        # Append domain-specific disclaimers if available
        if safety_disclaimers:
            response += "\n\n" + format_disclaimers(safety_disclaimers)

        new_state = state.copy()
        new_state["response"] = response
        new_state["status"] = "awaiting_slot"  # Next turn goes to interviewer for personalization
        new_state["suggested_replies"] = ["Personalise for me"]
        new_state["next_agent"] = None
        return new_state

    if intent_type == "journey" and journey_bundle:
        # Product cards are rendered by the frontend, so the text response
        # only needs the journey intro — no product listing.
        journey_response = f"# {journey_bundle['journey_name']}\n\n{journey_bundle['journey_description']}"

        # Add disclaimers
        if safety_disclaimers:
            journey_response += "\n\n" + format_disclaimers(safety_disclaimers)
        else:
            default_disclaimer = _get_default_disclaimer(domain_slug)
            if default_disclaimer:
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

    # Domain-aware config and persona for the main response flow
    main_persona = _get_persona(domain_slug)
    main_config = _get_domain_response_config(domain_slug)

    # Build problem block
    problem_block = ""
    if problem_display_name:
        problem_block = f"{problem_display_name}"
        if problem_description:
            problem_block += f" — {problem_description}"
    else:
        problem_block = main_config["fallback_problem_label"]

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

    system_prompt = f"""{main_persona} Generate a structured, deeply personalized response using **Markdown**.

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
(Layer 2 — Reframe, 2-3 sentences) Based on the problem description and key information, explain possible drivers or mechanisms behind the concern. Use hedging language — "may", "often", "could".

## What Can Help
(Layer 3 — Recommendations)

**{main_config["lifestyle_heading"]}**
- {main_config["lifestyle_guidance"]}

(Do NOT list product names or specific ingredients — the product cards handle that.)

## Important to Know
(Layer 4 — Safety, 1-3 bullets) Who should be cautious, what to monitor, when to consult a professional. Base this on the domain safety guidelines and any applied constraints.

---

**Formatting rules:**
- Use `##` headings exactly as shown above
- **Bold** key terms
- Bullets for lists
- Short paragraphs (2-3 sentences each)
- Total response: ~150-250 words
- NEVER list product names (product cards are rendered separately)
- NEVER greet the user

**Language guidelines:**
{main_config["language_guidelines"]}

**IMPORTANT: Respond in the same language as the user's message below.**
User's message: "{user_message}"

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
        default_disclaimer = _get_default_disclaimer(domain_slug)
        if default_disclaimer:
            final_response += "\n\n" + format_disclaimers(default_disclaimer)

    # Layer 5: Append domain-specific disclaimers programmatically
    if safety_disclaimers:
        final_response += "\n\n" + format_disclaimers(safety_disclaimers)

    # Build context-aware filter suggestions for post-completion refinement
    filter_suggestions = []

    # Budget: only suggest if user hasn't set one yet
    if not extracted_context.get("budget_max") and not extracted_context.get("budget"):
        # Detect currency from the returned products so the label matches the DB
        _currency_config = {
            "INR": ("₹", 1000),
            "USD": ("$", 50),
            "GBP": ("£", 40),
            "EUR": ("€", 45),
            "AUD": ("A$", 70),
            "CAD": ("C$", 65),
        }
        _currency = "USD"
        for _p in final_products:
            if _p.get("currency"):
                _currency = _p["currency"].upper()
                break
        _symbol, _threshold = _currency_config.get(_currency, ("$", 50))
        filter_suggestions.append(f"Under {_symbol}{_threshold}")

    # Domain-specific filter suggestions
    filter_suggestions.extend(
        _build_filter_suggestions(main_config, extracted_context, filled_attrs)
    )

    # Update state
    new_state = state.copy()
    new_state["response"] = final_response
    new_state["status"] = "completed"
    new_state["suggested_replies"] = filter_suggestions
    new_state["next_agent"] = None

    return new_state
