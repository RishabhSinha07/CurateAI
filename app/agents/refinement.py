import logging
from typing import Any, Dict, List
from pydantic import BaseModel, Field, field_validator

from app.agents.validators import parse_dict, parse_bool
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.agents.state import AgentState
from app.agents.llm import get_bedrock_llm

logger = logging.getLogger(__name__)

settings = get_settings()


class RefinementResponse(BaseModel):
    """Structured response from the Refinement detection agent."""
    intent: str = Field(
        description=(
            "One of: "
            "'refinement' if user wants to filter/adjust current results, "
            "'re_personalize' if user wants to restart the personalization interview for the same domain, "
            "'ingredient_info' if user is asking an educational question about an ingredient or supplement, "
            "'product_detail' if user is asking about a specific product from the shown recommendations, "
            "'new_topic' if user wants something completely different"
        )
    )
    new_constraints: Dict[str, Any] = Field(
        default_factory=dict,
        description="New constraints to add (e.g., budget, format preference). Only for refinement intent."
    )
    product_reference: str | None = Field(
        default=None,
        description="The name or phrase the user used to refer to a specific shown product. Only for product_detail intent."
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

    # Fast-path: if PDA is awaiting user confirmation (yes/no) or the user
    # just picked a product from the selection list, route directly to PDA
    # without invoking the classification LLM.
    if extracted_context.get("pda_pending_confirm"):
        new_state = state.copy()
        new_state["next_agent"] = "product_detail"
        return new_state

    has_products = bool(state.get("final_products"))
    product_count = len(state.get("final_products", []))
    # Read from extracted_context["shown_products"] (persisted across turns)
    # since initial_products/final_products start empty each turn.
    shown_products = extracted_context.get("shown_products") or []
    product_names = [p.get("name", "") for p in shown_products if p.get("name")]
    product_names_str = ", ".join(f'"{n}"' for n in product_names[:8])
    pda_last = extracted_context.get("pda_last_product", "")

    pda_context_block = ""
    if pda_last:
        pda_context_block = (
            f'The user was just discussing "{pda_last}". '
            'Follow-up questions like "are there side effects?", "is it vegan?", '
            '"how should I take it?" are about THAT product → product_detail.\n'
        )

    system_message = f"""You are analyzing what a user wants to do after seeing product recommendations.
The user has already been shown {product_count} product(s) in the "{domain_slug}" domain.
{f"Shown product names: {product_names_str}" if product_names else ""}
{pda_context_block}
Classify into ONE of five intents:

PRODUCT_DETAIL — user is asking about a specific shown product OR an educational ingredient question:
- Questions about a shown product: "tell me more about X", "what's in the X one", "is X vegan?", "how do I take X?"
- Pronouns or partial names: "tell me more about the sleep one", "is that one vegan?", "how should I take it?"
- Follow-up questions about the product just discussed: "are there side effects?", "what's the dosage?", "can I take it daily?"
- Educational ingredient questions: "how does collagen work?", "what does magnesium do?", "benefits of zinc"
- Set product_reference to the product name, ingredient, or phrase the user mentioned
- Do NOT use product_detail for navigation like "show me more", "other options", "different products" — those are REFINEMENT or NEW_TOPIC

INGREDIENT_INFO — Same as product_detail but only when no products exist (rare in refinement).

RE_PERSONALIZE — user wants to restart the personalization interview for the same domain:
- Keywords: "personalise", "personalize", "customise", "customize", "personalise for me", "personalize for me", "make it personal", "tailor this", "based on my needs", "for my needs"
- These users want the system to ask them questions (age, goals, preferences) to find better-matched products.

REFINEMENT — user wants to filter/adjust the current results without re-interviewing:
- Price/budget: "cheaper", "under ₹X", "under X", "under 1000", "more affordable", "budget", "less than X"
- Format: "in powder form", "capsules instead", "liquid version"
- Ingredient filters: "without fish", "vegan option", "no allergens"
- Allergy mentions: "I have a fish allergy", "allergic to dairy"
- Quantity: "show more", "other options", "alternatives"
- IMPORTANT: Any message that is purely a price/budget constraint (e.g. "under 1500", "below 500", "max 2000") is ALWAYS a refinement when the user has been shown products. These are filters on the current results, never a new topic.

NEW_TOPIC — user wants something completely different:
- Different health goal: "what about sleep?", "energy instead"
- Ending conversation: "thanks", "that's all", "goodbye"
- Completely unrelated: weather, general questions
- IMPORTANT: A bare budget like "under 1500" is NOT a new topic — it is a refinement filter on current results.

When extracting new_constraints (only for REFINEMENT), use these EXACT key names:
- "allergies": list of allergy strings, e.g. ["fish", "dairy"]
- "dietary_preference": string, e.g. "vegan", "vegetarian"
- "budget_max": number (strip currency symbol), e.g. 1000 for "under ₹1000"
- "format_preference": string, e.g. "capsule", "powder", "liquid"

Return intent as one of: "product_detail", "ingredient_info", "refinement", "re_personalize", "new_topic"
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

    if result.intent == "product_detail":
        # Product-specific question — route to PDA, preserve all state
        updated_context = {**extracted_context}
        updated_context["pda_product_reference"] = result.product_reference or user_message
        new_state["extracted_context"] = updated_context
        new_state["next_agent"] = "product_detail"
    elif result.intent == "ingredient_info":
        # If products are shown, redirect to PDA — it handles ingredient
        # questions with product context. Only use ingredient_info when
        # no products exist (shouldn't happen in refinement, but safety net).
        if shown_products:
            updated_context = {**extracted_context}
            updated_context["pda_product_reference"] = user_message
            new_state["extracted_context"] = updated_context
            new_state["next_agent"] = "product_detail"
        else:
            new_state["next_agent"] = "ingredient_info"
    elif result.intent == "refinement":
        # Filter the already-shown products in-memory instead of re-running
        # a full database search. This is faster and matches user expectation
        # ("filter what I'm looking at").
        current_status = state.get("status", "")
        constraints = result.new_constraints
        filtered = _filter_shown_products(shown_products, constraints)
        logger.info(
            f"Refinement in-memory filter: {len(shown_products)} → {len(filtered)} products, "
            f"constraints={constraints}"
        )

        new_state["extracted_context"] = {
            **extracted_context,
            **constraints,
            "_is_refinement_pass": True,
            "_resume_interview": current_status == "awaiting_slot",
        }
        new_state["final_products"] = filtered
        new_state["status"] = "refining"
        new_state["next_agent"] = "safety"
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


def _filter_shown_products(
    products: List[Dict[str, Any]],
    constraints: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Filter already-shown products in-memory using refinement constraints."""
    filtered = list(products)

    # Budget filter
    budget_max = constraints.get("budget_max")
    if budget_max is not None:
        budget_max = float(budget_max)
        filtered = [p for p in filtered if (p.get("price") or 0) <= budget_max]

    # Dietary preference — match against product description or attributes
    diet = constraints.get("dietary_preference")
    if diet:
        diet_lower = diet.lower()
        filtered = [
            p for p in filtered
            if diet_lower in (p.get("description") or "").lower()
            or diet_lower in str(p.get("attributes") or {}).lower()
        ]

    # Format preference — match against description or attributes
    fmt = constraints.get("format_preference")
    if fmt:
        fmt_lower = fmt.lower()
        filtered = [
            p for p in filtered
            if fmt_lower in (p.get("description") or "").lower()
            or fmt_lower in str(p.get("attributes") or {}).lower()
        ]

    # Allergy exclusion — exclude products mentioning the allergen
    allergies = constraints.get("allergies")
    if allergies and isinstance(allergies, list):
        def _has_allergen(product: Dict, allergens: List[str]) -> bool:
            text = (product.get("description") or "").lower()
            text += " " + str(product.get("attributes") or {}).lower()
            return any(a.lower() in text for a in allergens)
        filtered = [p for p in filtered if not _has_allergen(p, allergies)]

    return filtered
