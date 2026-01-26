from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.agents.state import AgentState

settings = get_settings()

# Descriptions explaining why each slot matters for recommendations.
# Used to help the LLM justify questions to the user.
SLOT_DESCRIPTIONS: Dict[str, str] = {
    "health_goal": (
        "The primary health outcome the user wants to achieve (e.g. better sleep, "
        "more energy, stronger immunity). This is the single most important factor "
        "for matching the right product."
    ),
    "skin_concern": (
        "The specific skin issue the user wants to address (e.g. wrinkles, dryness, "
        "dark spots, acne). Different collagen formulations target different concerns."
    ),
    "collagen_preference": (
        "Whether the user prefers marine collagen or a vegan collagen builder. "
        "Marine collagen contains fish-derived peptides; vegan builders use plant "
        "amino acids to stimulate the body's own collagen production."
    ),
    "gender": (
        "Some supplement formulations are tailored to men's or women's nutritional "
        "needs (e.g. iron and folate for women, zinc and lycopene for men)."
    ),
    "dietary_preference": (
        "Dietary restrictions like vegan, vegetarian, or allergen-free. Helps "
        "exclude products that contain animal-derived or allergenic ingredients."
    ),
    "budget": (
        "The user's price range. Helps narrow results to affordable options "
        "and avoids recommending products outside their comfort zone."
    ),
    "flavor_preference": (
        "Preferred flavors (e.g. tropical, berry, unflavored). Matters for "
        "powders and effervescents where taste affects daily compliance."
    ),
    "age_group": (
        "Age bracket helps select appropriate dosages and formulations, as "
        "nutritional needs shift across life stages."
    ),
}

# Example values for each slot so the LLM can guide the user.
SLOT_EXAMPLES: Dict[str, str] = {
    "health_goal": "sleep, energy, immunity, digestion, stress, weight management, hair health",
    "skin_concern": "acne, wrinkles, dryness, dark spots, aging, firmness, pigmentation, glow",
    "collagen_preference": "marine collagen (fish-derived) or vegan collagen builder (plant-based)",
    "gender": "male, female, or prefer not to say",
    "dietary_preference": "vegan, vegetarian, no restrictions",
    "budget": "a rough price range or 'no preference'",
    "flavor_preference": "tropical, berry, citrus, matcha, unflavored, no preference",
    "age_group": "under 25, 25-35, 35-50, over 50",
}


class InterviewerResponse(BaseModel):
    """Structured response from the Interviewer agent."""
    reasoning: str = Field(
        description="Brief internal explanation of extraction and decision logic. Fill this FIRST."
    )
    extracted_values: Dict[str, Any] = Field(
        default_factory=dict,
        description="Slot names mapped to values extracted from the user's message"
    )
    missing_slots: List[str] = Field(
        default_factory=list,
        description="Required slot names still unfilled after extraction"
    )
    suggested_optional_slots: List[str] = Field(
        default_factory=list,
        description=(
            "Optional slot names that would meaningfully improve recommendations "
            "given what we already know. Only include slots you believe are relevant."
        ),
    )
    ready_to_search: bool = Field(
        default=False,
        description=(
            "True when the user signals they want to skip remaining questions "
            "and search with whatever information is available "
            "(e.g. 'just show me products', 'that's all I know', 'skip')."
        ),
    )
    question: Optional[str] = Field(
        default=None,
        description=(
            "A natural, conversational follow-up that asks about missing slots. "
            "Should briefly explain WHY the information helps. "
            "MUST be non-null whenever missing_slots is non-empty. "
            "Only null when all slots are genuinely filled or user wants to skip."
        ),
    )


def get_interviewer_model():
    """Initialize the Bedrock model for interviewing."""
    llm = ChatBedrock(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        model_kwargs={"temperature": 0},
    )
    return llm.with_structured_output(InterviewerResponse)


def _build_slot_reference(slots: List[str]) -> str:
    """Build a readable reference block describing each slot and example values."""
    lines = []
    for slot in slots:
        desc = SLOT_DESCRIPTIONS.get(slot, slot.replace("_", " "))
        examples = SLOT_EXAMPLES.get(slot, "")
        entry = f"  - {slot}: {desc}"
        if examples:
            entry += f"\n    Examples: {examples}"
        lines.append(entry)
    return "\n".join(lines)


SYSTEM_PROMPT = """\
You are a friendly, knowledgeable wellness consultant helping a user find the \
right supplement. Your job in this step is to understand what the user needs \
before we search for products.

Your approach:
1. EXTRACT only values the user has **explicitly and clearly stated**. \
   Do NOT infer, assume, or guess slot values. \
   For example: "I want protein" tells you the user wants a protein product, \
   but it does NOT tell you their health_goal — do not fill health_goal with \
   a guess like "weight management" or "muscle building". \
   Similarly, "skin health" does NOT imply "anti-aging" — do not guess specific concerns. \
   Only fill a slot when the user's words directly and unambiguously match it.
2. IDENTIFY which required slots are still missing after extraction.
3. ASK about missing slots in a single, natural follow-up message. For each \
   piece of information you ask for, include a brief reason explaining why it \
   helps you recommend the right product. Keep it concise — one or two \
   sentences per slot, woven into a conversational message (not a bulleted \
   interrogation).
4. If you believe any optional slots would meaningfully improve the \
   recommendation given the context so far, include them in your question \
   too. For example, if the user mentions they are vegan, asking about \
   dietary preference is unnecessary — but asking about flavor preference \
   for a powder product could be very helpful.
5. RESPECT the user's pace. If the user indicates they don't want to answer \
   more questions (e.g. "just search", "that's enough", "I don't know", \
   "show me what you have"), set ready_to_search to true and do NOT ask \
   another question. Use whatever information you already have.
6. When there are missing required slots, you MUST always generate a question \
   — never leave the question field empty or null while slots are unfilled.

When the user gives a short answer (like "capsule", "oily", "powder"), it is \
almost certainly answering the previous question. Map it to the correct slot \
based on the conversation context.

Do NOT repeat questions for slots that are already filled.

TONE: Do NOT start your question with filler like "Great!", "Sure!", \
"Awesome!", or "I'd love to help!". Get straight to the point — ask what \
you need and briefly say why.\
"""


async def interviewer_agent(state: AgentState) -> AgentState:
    """
    Manages the consultation phase: extracts information and asks clarifying questions.

    The agent extracts slot values from the user's message, asks about remaining
    required (and optionally relevant) slots with brief justifications, and
    detects when the user wants to skip ahead to search.
    """
    domain_config = state.get("domain_config") or {}
    required_slots = domain_config.get("required_slots", [])
    optional_slots = domain_config.get("optional_slots", [])
    extracted_context = state.get("extracted_context", {})
    previous_response = state.get("response")

    # Identify what we still need
    already_filled = set(extracted_context.keys())
    missing_required = [s for s in required_slots if s not in already_filled]
    unfilled_optional = [s for s in optional_slots if s not in already_filled]

    # Fast path: nothing missing and we're not waiting for a slot answer
    if not missing_required and state["status"] != "awaiting_slot":
        new_state = state.copy()
        new_state["next_agent"] = "search"
        return new_state

    # --- Build the human message with full context ---

    # First-pass detection: initial_products were fetched by the previous node.
    is_first_pass = bool(state.get("initial_products"))

    # Slot reference for required slots
    all_relevant_slots = list(dict.fromkeys(missing_required + unfilled_optional))
    slot_reference = _build_slot_reference(all_relevant_slots)

    # Previous question context for short-answer mapping
    previous_question_section = ""
    if previous_response and state.get("status") == "awaiting_slot":
        previous_question_section = (
            f'\nPrevious question you asked the user:\n  "{previous_response}"\n'
            "The user's message below is likely answering this question.\n"
        )

    filled_summary = (
        "\n".join(f"  - {k}: {v}" for k, v in extracted_context.items())
        if extracted_context
        else "  (none yet)"
    )

    # When initial products are being shown alongside this message, tell the
    # LLM so it can write a question that flows naturally after the preamble.
    first_pass_note = ""
    if is_first_pass:
        first_pass_note = (
            "\nNOTE: The user is already seeing a few popular products from "
            "this domain. Your question will appear right below that list. "
            "Do NOT greet the user or repeat that products are shown — just "
            "ask your questions directly. Start with something like "
            '"To narrow things down...", "To find the best match..." or '
            "similar.\n"
        )

    user_message = f"""\
Domain: {state.get('domain_slug')}

Information already collected:
{filled_summary}

Required slots still needed: {missing_required or '(all filled)'}
Optional slots available: {unfilled_optional or '(none)'}

Slot reference:
{slot_reference}
{previous_question_section}{first_pass_note}
User's latest message: "{state['user_message']}"

Respond with your extraction and follow-up question (if any).\
"""

    model = get_interviewer_model()
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]
    result: InterviewerResponse = await model.ainvoke(messages)

    # --- Update state ---
    new_state = state.copy()
    new_state["extracted_context"] = {**extracted_context, **result.extracted_values}
    new_state["missing_slots"] = result.missing_slots

    # Determine whether to continue asking or proceed to search.
    # We only keep asking if the LLM actually produced a question.
    # If it suggested optional slots but didn't write a question, just search.
    has_question = bool(result.question and result.question.strip())
    should_search = (
        result.ready_to_search
        or not has_question
    )

    if should_search:
        new_state["response"] = None
        new_state["status"] = "collecting_info"
        new_state["next_agent"] = "search"
        new_state["optional_slot_hint"] = None
    else:
        question_text = result.question  # guaranteed non-empty here

        if is_first_pass:
            # Compact preamble that sits between the product cards and the
            # interviewer's first question.  The LLM has been told to skip
            # greetings and start directly with the ask.
            domain_name = (state.get("domain_slug") or "this category").replace("-", " ")
            preamble = (
                f"Here are some popular **{domain_name}** products to get you started.\n\n"
                "---\n\n"
                "I can find a better match with a couple of quick questions:\n\n"
            )
            question_text = preamble + question_text

        new_state["response"] = question_text
        new_state["status"] = "awaiting_slot"
        new_state["next_agent"] = None  # End turn — wait for user input

    return new_state
