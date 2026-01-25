from typing import List, Optional
from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock

from app.config import get_settings
from app.agents.state import AgentState

settings = get_settings()


def _format_price(price: float, currency: str) -> str:
    """Format price with appropriate currency symbol."""
    currency_symbols = {
        "USD": "$",
        "INR": "₹",
        "EUR": "€",
        "GBP": "£",
        "CAD": "CA$",
        "AUD": "A$",
        "JPY": "¥",
    }

    symbol = currency_symbols.get(currency.upper(), currency)

    # For currencies like JPY that don't use decimals
    if currency.upper() in ["JPY", "KRW"]:
        return f"{symbol}{price:.0f}"

    return f"{symbol}{price:.2f}"


class SafetyResponse(BaseModel):
    """Structured response from the Safety agent."""
    response: str = Field(description="The final user-facing response with recommendations")
    disclaimers: List[str] = Field(description="Any safety disclaimers that should be appended")
    contains_medical_claims: bool = Field(description="Whether the response contains medical claims that need disclaimers")
    is_safe: bool = Field(description="Whether the response is safe to send")


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
    4. Handles out-of-scope requests gracefully
    """
    status = state.get("status", "")
    domain_config = state.get("domain_config") or {}
    final_products = state.get("final_products", [])
    extracted_context = state.get("extracted_context", {})
    safety_disclaimers = domain_config.get("safety_disclaimers", [])

    # Handle out-of-scope requests
    if status == "out_of_scope":
        new_state = state.copy()
        new_state["response"] = "I'm a wellness product consultant and can help you find supplements, vitamins, and health products. Is there something in that area I can help you with today?"
        new_state["status"] = "completed"
        new_state["next_agent"] = None
        return new_state

    # Handle no results
    if not final_products:
        new_state = state.copy()
        new_state["response"] = "I couldn't find products that match your specific requirements. Could you tell me more about what you're looking for, or would you like me to broaden the search?"
        new_state["status"] = "completed"
        new_state["next_agent"] = None
        return new_state

    # Format products for the response
    products_info = []
    for p in final_products:
        formatted_price = _format_price(p['price'], p['currency'])
        info = f"""
**{p['name']}** by {p['brand']}
- Price: {formatted_price}
- Why it's a good fit: {', '.join(p.get('match_reasons', ['Matches your preferences']))}
- [View Product]({p.get('product_url', '#')})
"""
        products_info.append(info)

    products_text = "\n".join(products_info)

    system_prompt = f"""You are a wellness consultant for CurateAI. Generate a clear, professional response presenting product recommendations to the user.

User's Context/Preferences:
{extracted_context}

Products to Recommend:
{products_text}

Domain-Specific Safety Guidelines:
{safety_disclaimers}

Your Tasks:
1. RESPOND: Write a direct, professional response that:
   - Gets straight to the recommendations without preamble or greetings
   - Presents the top recommendations with brief highlights
   - Explains why each product fits their needs
   - Keep it concise and focused on the products

2. SAFETY CHECK: Identify if your response:
   - Makes medical claims (e.g., "cures", "treats", "prevents disease")
   - Suggests diagnosis or treatment
   - Could be interpreted as medical advice

3. DISCLAIMERS: Based on the domain safety guidelines, add appropriate disclaimers.

Guidelines:
- Keep the response concise and professional
- NO greetings like "Hey there!" or "Hello!" - get straight to the point
- NO acknowledgment phrases like "I heard you're looking for..." - just present the recommendations
- Focus on benefits without making medical claims
- Use phrases like "may support", "designed to help", "formulated for"
- Never claim products treat, cure, or prevent any disease
- Always encourage consulting a healthcare professional for medical concerns
"""

    model = get_safety_model()
    result: SafetyResponse = await model.ainvoke(system_prompt)

    # Build final response
    final_response = result.response

    # Prepend optional slot hint if present
    optional_slot_hint = state.get("optional_slot_hint")
    if optional_slot_hint:
        final_response = f"{optional_slot_hint}\n\n{final_response}"

    # Append disclaimers if needed
    if result.disclaimers:
        disclaimer_text = "\n\n---\n" + "\n".join(f"⚠️ {d}" for d in result.disclaimers)
        final_response += disclaimer_text
    elif result.contains_medical_claims:
        # Default disclaimer for health products
        final_response += "\n\n---\n⚠️ These statements have not been evaluated by the FDA. These products are not intended to diagnose, treat, cure, or prevent any disease. Please consult with a healthcare professional before starting any new supplement regimen."

    # Update state
    new_state = state.copy()
    new_state["response"] = final_response
    new_state["status"] = "completed"
    new_state["next_agent"] = None

    return new_state
