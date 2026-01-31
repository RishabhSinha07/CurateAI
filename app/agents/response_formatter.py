"""
Response formatting utilities for consistent markdown output across agents.

This module provides functions to format agent responses with proper markdown
structure, including product recommendations, constraints, and disclaimers.
"""

from typing import Any, Dict, List, Optional


def format_price(price: float, currency: str) -> str:
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


def format_product_card(
    product: Dict[str, Any],
    rank: Optional[int] = None,
    include_usage_guidance: bool = False
) -> str:
    """
    Format a single product as a markdown card.

    Args:
        product: Product dictionary with name, brand, price, etc.
        rank: Optional rank number (e.g., 1, 2, 3)
        include_usage_guidance: Whether to include usage guidance (for journey bundles)

    Returns:
        Formatted markdown string for the product
    """
    # Build header with optional rank
    header = f"**{product['name']}**"
    if product.get('brand'):
        header += f" by *{product['brand']}*"
    if rank:
        header = f"### {rank}. {header}"
    else:
        header = f"### {header}"

    lines = [header, ""]

    # Price
    if product.get('price'):
        formatted_price = format_price(product['price'], product.get('currency', 'USD'))
        lines.append(f"**Price:** {formatted_price}")

    # Match reasons (why this product fits)
    match_reasons = product.get('match_reasons', [])
    if match_reasons:
        lines.append("")
        lines.append("**Why it's a good fit:**")
        for reason in match_reasons:
            lines.append(f"- {reason}")

    # Usage guidance (for journey bundles)
    if include_usage_guidance and product.get('usage_guidance'):
        lines.append("")
        lines.append(f"**Usage guidance:** {product['usage_guidance']}")

    # Product link
    if product.get('product_url'):
        lines.append("")
        lines.append(f"[View Product]({product['product_url']})")

    lines.append("")  # Spacing between cards
    return "\n".join(lines)


def format_product_recommendations(
    products: List[Dict[str, Any]],
    include_ranks: bool = True,
    include_usage_guidance: bool = False,
    title: str = "Recommended Products"
) -> str:
    """
    Format a list of product recommendations.

    Args:
        products: List of product dictionaries
        include_ranks: Whether to number the products
        include_usage_guidance: Whether to include usage guidance
        title: Section title

    Returns:
        Formatted markdown string with all products
    """
    if not products:
        return ""

    lines = [f"## {title}", ""]

    for i, product in enumerate(products, 1):
        rank = i if include_ranks else None
        card = format_product_card(
            product,
            rank=rank,
            include_usage_guidance=include_usage_guidance
        )
        lines.append(card)

    return "\n".join(lines)


def format_constraints_applied(constraints: List[str]) -> str:
    """
    Format safety constraints that were applied.

    Args:
        constraints: List of constraint strings (e.g., ["Medical: Pregnancy", "Diet: Vegan"])

    Returns:
        Formatted markdown string
    """
    if not constraints:
        return ""

    lines = [
        "### Safety Filters Applied",
        "",
        "All recommendations have been filtered based on your requirements:",
        ""
    ]

    for constraint in constraints:
        lines.append(f"- ✓ {constraint}")

    lines.append("")
    return "\n".join(lines)


def format_journey_bundle(
    journey_name: str,
    journey_description: str,
    products: List[Dict[str, Any]]
) -> str:
    """
    Format a journey bundle with products and guidance.

    Args:
        journey_name: Name of the journey
        journey_description: Description of the journey
        products: List of products with usage guidance

    Returns:
        Formatted markdown string
    """
    lines = [
        f"# {journey_name}",
        "",
        journey_description,
        "",
        "---",
        "",
        "## Your Complete Journey Bundle",
        ""
    ]

    for i, product in enumerate(products, 1):
        card = format_product_card(product, rank=i, include_usage_guidance=True)
        lines.append(card)

    return "\n".join(lines)


def format_intro_with_constraints(
    constraints: List[str],
    domain_name: Optional[str] = None
) -> str:
    """
    Format an intro message mentioning applied constraints.

    Args:
        constraints: List of applied constraints
        domain_name: Optional domain name to mention

    Returns:
        Formatted intro paragraph
    """
    if not constraints:
        return ""

    # Build constraint summary
    constraint_parts = []
    for c in constraints:
        if "Medical:" in c:
            constraint_parts.append("your medical requirements")
        elif "Diet:" in c:
            diet = c.replace("Diet: ", "").lower()
            constraint_parts.append(f"{diet} diet")
        elif "Allergy:" in c:
            allergy = c.replace("Allergy: ", "").lower()
            constraint_parts.append(f"{allergy}-free")

    if constraint_parts:
        constraints_text = ", ".join(constraint_parts)
        return f"All products below are safe for {constraints_text}.\n\n"

    return ""


def format_disclaimers(disclaimers: List[str]) -> str:
    """
    Format safety disclaimers.

    Args:
        disclaimers: List of disclaimer strings

    Returns:
        Formatted markdown string with disclaimers
    """
    if not disclaimers:
        return ""

    lines = ["---", ""]
    for disclaimer in disclaimers:
        lines.append(f"⚠️ {disclaimer}")
        lines.append("")

    return "\n".join(lines)


def format_no_results_message(
    extracted_context: Dict[str, Any],
    has_constraints: bool = False
) -> str:
    """
    Format a helpful message when no products are found.

    Args:
        extracted_context: User's extracted context
        has_constraints: Whether the user has applied constraints

    Returns:
        Formatted markdown message
    """
    lines = ["## No Products Found", ""]

    if has_constraints:
        lines.append(
            "I couldn't find products that match all your specific requirements. "
            "Here are some options:"
        )
        lines.append("")
        lines.append("1. **Relax some constraints** - Would you like to see products that don't meet all criteria?")
        lines.append("2. **Broaden the search** - I can look in a wider category")
        lines.append("3. **Try different criteria** - Tell me more about what you're looking for")
    else:
        lines.append(
            "I couldn't find products matching your request. "
            "Could you provide more details about what you're looking for?"
        )

    lines.append("")
    return "\n".join(lines)


def format_out_of_scope_message() -> str:
    """Format a message for out-of-scope requests."""
    return (
        "I'm a wellness product consultant specialized in supplements, vitamins, and health products. "
        "\n\nIs there something in that area I can help you with today?"
    )
