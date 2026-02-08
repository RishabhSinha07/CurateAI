from typing import Any
from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.agents.state import AgentState
from app.db.repositories.journey_bundle import JourneyBundleRepository
from app.db.repositories.product import ProductRepository
from app.services.embeddings import generate_embedding_async

settings = get_settings()


class JourneyBundleProduct(BaseModel):
    """A product in a journey bundle with usage guidance."""
    product_id: str
    category: str
    usage_guidance: str


class JourneyBundleResponse(BaseModel):
    """Structured response for journey bundle generation."""
    journey_name: str = Field(description="Name of the journey")
    journey_description: str = Field(description="Description of what this journey helps with")
    products: list[JourneyBundleProduct] = Field(
        description="List of products with usage guidance for each"
    )
    reasoning: str = Field(description="Brief explanation of why these products were selected")


def get_journey_model():
    """Initialize the Bedrock model for journey bundle generation."""
    llm = ChatBedrock(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        model_kwargs={"temperature": 0.3},  # Slightly higher for product selection variety
    )
    return llm.with_structured_output(JourneyBundleResponse)


async def journey_agent(state: AgentState, db: AsyncSession) -> AgentState:
    """
    Handles journey-based product recommendations.
    
    This agent:
    1. Matches user message to a journey bundle using keywords
    2. Searches for products matching the journey's categories/tags
    3. Generates usage guidance for each product
    4. Returns comprehensive bundle with guidance
    """
    domain_slug = state.get("domain_slug")
    user_message = state.get("user_message")

    if not domain_slug:
        # Fallback if no domain detected
        new_state = state.copy()
        new_state["status"] = "out_of_scope"
        new_state["next_agent"] = "safety"
        return new_state

    # Find matching journey bundle
    journey_repo = JourneyBundleRepository(db)
    matched_journey = await journey_repo.match_by_keywords(domain_slug, user_message)
    
    if not matched_journey:
        # No journey matched, fall back to regular query flow
        new_state = state.copy()
        new_state["intent_type"] = "query"
        new_state["status"] = "collecting_info"
        new_state["next_agent"] = "interviewer"
        return new_state
    
    # Search for products matching journey categories
    product_repo = ProductRepository(db)
    
    # Build search query from journey categories
    search_query = f"{matched_journey.name}. " + " ".join(matched_journey.product_categories)
    query_embedding = await generate_embedding_async(search_query)
    
    # Perform hybrid search with low threshold to ensure we get results
    search_results = await product_repo.hybrid_search(
        query_embedding=query_embedding,
        filters=None,
        limit=50,  # Get more products to filter by categories
        min_similarity=-1.0  # Use negative threshold to catch EVERYTHING
    )
    
    # Filter products by categories and tags
    category_products = {}
    all_products = []  # Keep track of all search results
    
    for product, similarity in search_results:
        # Store all products for fallback
        product_data = {
            "id": str(product.id),
            "name": product.name,
            "brand": product.brand,
            "description": product.description,
            "price": float(product.price) if product.price else None,
            "currency": product.currency,
            "product_url": product.product_url,
            "image_url": product.image_url,
            "attributes": product.attributes,
            "similarity": similarity
        }
        all_products.append(product_data)
        
        # Check if product matches any of the journey categories
        product_attrs = product.attributes or {}
        product_category = product_attrs.get("category", "").lower()
        product_name_lower = product.name.lower()
        product_desc_lower = (product.description or "").lower()
        
        # Try to match product to journey categories
        for journey_category in matched_journey.product_categories:
            journey_cat_lower = journey_category.lower()
            
            # Check in category attribute, name, and description
            if (journey_cat_lower in product_category or 
                journey_cat_lower in product_name_lower or 
                journey_cat_lower in product_desc_lower):
                
                # Add to category if not already added
                if journey_category not in category_products:
                    category_products[journey_category] = {
                        **product_data,
                        "category": journey_category
                    }
                    break
    
    # Generate usage guidance using LLM
    products_data = list(category_products.values())
    
    # Fallback: if we didn't match enough products by category, use top search results
    if len(products_data) < len(matched_journey.product_categories):
        # Add top products that weren't already matched
        for product in all_products[:len(matched_journey.product_categories)]:
            if product["id"] not in [p["id"] for p in products_data]:
                # Guess the most likely category from product name
                matched_category = None
                product_name_lower = product["name"].lower()
                for journey_category in matched_journey.product_categories:
                    if journey_category.lower() in product_name_lower:
                        matched_category = journey_category
                        break
                
                if not matched_category:
                    # Use first unmatched category
                    used_categories = {p["category"] for p in products_data}
                    remaining = [c for c in matched_journey.product_categories if c not in used_categories]
                    matched_category = remaining[0] if remaining else matched_journey.product_categories[0]
                
                products_data.append({
                    **product,
                    "category": matched_category
                })
    
    if not products_data:
        # No products found, fall back to query flow
        new_state = state.copy()
        new_state["intent_type"] = "query"
        new_state["status"] = "collecting_info"
        new_state["next_agent"] = "interviewer"
        return new_state
    
    # Build prompt for LLM to generate bundle with guidance
    guidance_templates = matched_journey.guidance_templates
    products_summary = "\n".join([
        f"- ID: {p['id']}, Name: {p['name']}, Category: {p['category']}, Description: {p['description'][:100] if p['description'] else 'No description'}"
        for p in products_data
    ])
    
    system_prompt = f"""You are creating a comprehensive product bundle for a customer journey.

Journey: {matched_journey.name}
Description: {matched_journey.description}

Available Products:
{products_summary}

Guidance Templates (use these as reference):
{guidance_templates}

Your task:
1. Select the best products from the list above for this journey
2. For each product you select, you MUST use the exact ID from the product list
3. For each product, create personalized usage guidance based on:
   - The journey context
   - The product's specific features/benefits
   - The guidance template for that category (if available)
   - How it fits into the overall journey

User's Message: "{user_message}"

IMPORTANT: When selecting products, use the exact product IDs provided in the Available Products list above. Do not make up or modify product IDs.

Create a bundle that helps this customer succeed in their journey."""

    model = get_journey_model()
    result: JourneyBundleResponse = await model.ainvoke(system_prompt)
    
    # Map LLM response products back to full product data
    final_products = []
    for bundle_product in result.products:
        # Find the matching product in our data
        product_data = next(
            (p for p in products_data if p["id"] == bundle_product.product_id),
            None
        )
        if product_data:
            final_products.append({
                **product_data,
                "usage_guidance": bundle_product.usage_guidance,
                "match_reasons": [f"Essential for {matched_journey.name}"]
            })
    
    # Update state
    new_state = state.copy()
    new_state["intent_type"] = "journey"
    new_state["journey_type"] = matched_journey.journey_id
    new_state["journey_bundle"] = {
        "journey_name": result.journey_name,
        "journey_description": result.journey_description,
        "products": final_products
    }
    new_state["final_products"] = final_products
    new_state["status"] = "completed"
    new_state["next_agent"] = "safety"
    
    return new_state
