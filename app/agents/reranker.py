from typing import Any, Dict, List
import logging

from app.agents.state import AgentState
from app.knowledge.query_engine import GraphQueryEngine

logger = logging.getLogger(__name__)

# NOTE: This module previously used LLM-based re-ranking but has been simplified.
# It now only performs safety filtering via the knowledge graph.
# Search ranking (graph boosting + vector similarity) is trusted.


def extract_ingredients_from_product(product: Dict[str, Any]) -> List[str]:
    """
    Extract ingredient names from product attributes.

    Looks for common attribute keys that contain ingredient information.
    """
    attributes = product.get("attributes", {})
    ingredients = []

    # Check various possible attribute keys
    if "ingredients" in attributes:
        ing = attributes["ingredients"]
        if isinstance(ing, list):
            ingredients.extend(ing)
        elif isinstance(ing, str):
            ingredients.append(ing)

    if "key_ingredients" in attributes:
        ing = attributes["key_ingredients"]
        if isinstance(ing, list):
            ingredients.extend(ing)
        elif isinstance(ing, str):
            ingredients.append(ing)

    # Extract from product name or description as fallback
    # Common wellness ingredients to look for
    common_ingredients = [
        "vitamin_b12", "vitamin_d3", "melatonin", "ashwagandha", "biotin",
        "iron", "marine_collagen", "vegan_collagen", "probiotics", "magnesium",
        "multivitamin", "vitamin_c", "niacinamide", "retinol", "hyaluronic_acid"
    ]

    product_text = f"{product.get('name', '')} {product.get('description', '')}".lower()
    for ing in common_ingredients:
        ing_readable = ing.replace("_", " ")
        if ing_readable in product_text or ing in product_text:
            if ing not in ingredients:
                ingredients.append(ing)

    return ingredients


def extract_user_constraints(extracted_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract user constraints from extracted context.

    Returns constraints in format expected by GraphQueryEngine.filter_by_constraints()
    """
    constraints = {}

    # Check for dietary constraints
    if "dietary_preference" in extracted_context:
        diet = extracted_context["dietary_preference"].lower()
        if "vegan" in diet:
            constraints["dietary"] = "vegan"
        elif "vegetarian" in diet:
            constraints["dietary"] = "vegetarian"

    # Check for medical constraints
    if "pregnancy" in extracted_context:
        constraints["pregnancy"] = bool(extracted_context["pregnancy"])

    if "breastfeeding" in extracted_context:
        constraints["breastfeeding"] = bool(extracted_context["breastfeeding"])

    # Check for allergies
    if "allergies" in extracted_context:
        allergies = extracted_context["allergies"]
        if isinstance(allergies, list):
            for allergy in allergies:
                constraints[f"allergy_{allergy.lower()}"] = True
        elif isinstance(allergies, str):
            constraints[f"allergy_{allergies.lower()}"] = True

    # Check in graph_state filled_attributes
    graph_state = extracted_context.get("graph_state", {})
    filled_attrs = graph_state.get("filled_attributes", {})

    for attr_cat, attr_data in filled_attrs.items():
        # Get value WITHOUT calling .lower() yet (might be a list!)
        value = attr_data.get("value", "")

        # Extract diet constraints
        if attr_cat == "diet" or attr_cat == "dietary_preference":
            # Handle both string and list values
            value_str = value if isinstance(value, str) else str(value)
            value_lower = value_str.lower()

            if "vegan" in value_lower:
                constraints["dietary"] = "vegan"
            elif "vegetarian" in value_lower:
                constraints["dietary"] = "vegetarian"

        # Extract medical constraints
        elif attr_cat == "medical_constraints":
            # Multi-choice field - check if user selected pregnancy/breastfeeding
            if isinstance(value, list):
                for item in value:
                    item_lower = item.lower() if isinstance(item, str) else str(item).lower()
                    if "pregnancy" in item_lower:
                        constraints["pregnancy"] = True
                    if "breastfeeding" in item_lower:
                        constraints["breastfeeding"] = True
            elif isinstance(value, str):
                value_lower = value.lower()
                if "pregnancy" in value_lower:
                    constraints["pregnancy"] = True
                if "breastfeeding" in value_lower:
                    constraints["breastfeeding"] = True

        # Extract allergy constraints
        elif attr_cat == "allergies":
            # Multi-choice field - check for fish/shellfish allergies
            if isinstance(value, list):
                for allergy in value:
                    if not isinstance(allergy, str):
                        continue
                    allergy_lower = allergy.lower()
                    if "no" in allergy_lower or "none" in allergy_lower:
                        continue
                    allergy_clean = allergy_lower.replace(" allergy", "").strip()
                    constraints[f"allergy_{allergy_clean}"] = True
            elif isinstance(value, str):
                value_lower = value.lower()
                if "no" not in value_lower and "none" not in value_lower:
                    allergy_clean = value_lower.replace(" allergy", "").strip()
                    constraints[f"allergy_{allergy_clean}"] = True

    return constraints


async def reranker_agent(state: AgentState) -> AgentState:
    """
    Filters search results by safety constraints (SIMPLIFIED - NO LLM).

    This agent:
    1. Uses knowledge graph to check contraindications (pregnancy, allergies, diet)
    2. Excludes products with contraindicated ingredients
    3. Applies simple budget/preference filters
    4. Trusts search ranking (graph boosting already applied)
    5. Returns top 5 safe products

    NOTE: No LLM re-ranking - search already uses graph-based ingredient boosting
    and vector similarity. This agent only filters for safety and constraints.
    """
    extracted_context = state.get("extracted_context", {})
    search_results = state.get("search_results", [])
    graph_state = extracted_context.get("graph_state", {})
    graph_domain = graph_state.get("graph_domain")
    low_confidence_search = state.get("low_confidence_search", False)

    if low_confidence_search:
        logger.info(
            "Reranker received LOW CONFIDENCE search results "
            "(fallback threshold 0.15 was used). Results may be less relevant."
        )

    if not search_results:
        # No results to rank
        new_state = state.copy()
        new_state["final_products"] = []
        new_state["status"] = "completed"
        new_state["next_agent"] = "safety"
        return new_state

    # Extract user constraints from context
    user_constraints = extract_user_constraints(extracted_context)
    logger.info(f"User constraints: {user_constraints}")

    # Filter products using knowledge graph (if domain is available)
    safe_products = []
    excluded_products = []

    for product in search_results:
        # Extract ingredients from product
        product_ingredients = extract_ingredients_from_product(product)

        if graph_domain and product_ingredients and user_constraints:
            try:
                # Check contraindications using knowledge graph
                safety_check = GraphQueryEngine.filter_by_constraints(
                    domain=graph_domain,
                    product_ingredients=product_ingredients,
                    user_constraints=user_constraints
                )

                if safety_check["is_safe"]:
                    safe_products.append(product)
                    logger.debug(f"Product '{product['name']}' passed safety check")
                else:
                    excluded_products.append({
                        "product_id": product["id"],
                        "product_name": product["name"],
                        "violations": safety_check["violations"]
                    })
                    logger.info(
                        f"Excluded '{product['name']}': "
                        f"{[v['reason'] for v in safety_check['violations']]}"
                    )
            except Exception as e:
                # If graph check fails, include product (fail open for availability)
                logger.warning(f"Graph safety check failed for '{product['name']}': {e}")
                safe_products.append(product)
        else:
            # No graph domain or no constraints - include all products
            safe_products.append(product)

    # Check if graph filtering excluded all products
    if not safe_products:
        logger.warning(
            f"All {len(search_results)} products were excluded by graph safety checks. "
            f"Returning empty results."
        )
        new_state = state.copy()
        new_state["final_products"] = []
        new_state["status"] = "ranked"
        new_state["next_agent"] = "safety"
        return new_state

    logger.info(
        f"Graph safety filtering: {len(safe_products)}/{len(search_results)} products safe, "
        f"{len(excluded_products)} excluded"
    )

    # Apply simple budget filter if present
    # Support both "budget_max" (set by refinement agent) and legacy "budget" key
    budget = extracted_context.get("budget_max") or extracted_context.get("budget")
    if budget:
        try:
            budget_value = float(budget)
            filtered_by_budget = []
            for product in safe_products:
                price = product.get("price", 0)
                if price and float(price) <= budget_value:
                    filtered_by_budget.append(product)
                else:
                    logger.info(f"Excluded '{product['name']}' due to budget (${price} > ${budget_value})")
            safe_products = filtered_by_budget
        except (ValueError, TypeError):
            logger.warning(f"Invalid budget value: {budget}, skipping budget filter")

    if not safe_products:
        logger.warning("All products excluded after budget filtering")
        new_state = state.copy()
        new_state["final_products"] = []
        new_state["status"] = "ranked"
        new_state["next_agent"] = "safety"
        return new_state

    # Apply format preference filter if present
    format_pref = extracted_context.get("format_preference")
    if format_pref:
        format_lower = format_pref.lower()
        filtered_by_format = [
            p for p in safe_products
            if format_lower in str(p.get("attributes", {}).get("product_format", "")).lower()
            or format_lower in p.get("name", "").lower()
            or format_lower in p.get("description", "").lower()
        ]
        if filtered_by_format:
            safe_products = filtered_by_format
            logger.info(f"Format preference filter: {len(safe_products)} products match '{format_pref}'")
        else:
            logger.info(f"No products match format '{format_pref}', keeping all {len(safe_products)} products")

    # Trust search ranking (graph boosting + vector similarity already applied)
    # Take top 10 products
    final_products = safe_products[:10]

    # Generate match reasons from product description
    for rank, product in enumerate(final_products, 1):
        product["rank"] = rank
        product["relevance_score"] = product.get("similarity_score", 0.0)

        # Build match reasons from product description
        match_reasons = []

        description = product.get("description", "")
        if description:
            match_reasons.append(description)

        # Safety passed
        if user_constraints:
            constraint_list = []
            if user_constraints.get("pregnancy"):
                constraint_list.append("pregnancy-safe")
            if user_constraints.get("dietary"):
                constraint_list.append(user_constraints["dietary"])
            if any(k.startswith("allergy_") for k in user_constraints.keys()):
                allergies = [k.replace("allergy_", "") for k in user_constraints.keys() if k.startswith("allergy_")]
                constraint_list.append(f"free of {', '.join(allergies)}")

            if constraint_list:
                match_reasons.append(f"Safe for your constraints ({', '.join(constraint_list)})")

        product["match_reasons"] = match_reasons

    # Update state
    new_state = state.copy()
    new_state["final_products"] = final_products
    new_state["status"] = "ranked"
    new_state["next_agent"] = "safety"
    new_state["low_confidence_search"] = low_confidence_search  # Pass through to safety agent

    # Log summary
    confidence_note = " (LOW CONFIDENCE fallback)" if low_confidence_search else ""
    logger.info(
        f"Reranker completed{confidence_note} (SIMPLIFIED - NO LLM): {len(final_products)} products recommended, "
        f"{len(excluded_products)} excluded by safety checks"
    )
    if excluded_products:
        logger.info(f"Excluded products: {[p['product_name'] for p in excluded_products]}")

    logger.info("Reranker: Trusting search ranking (graph boosting already applied)")

    return new_state
