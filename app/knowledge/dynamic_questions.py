"""
Dynamic question generation for attributes without predefined questions.

Uses LLM to generate natural questions based on attribute metadata when
ELICITS_QUESTION edges are missing from the knowledge graph.
"""

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from app.agents.validators import parse_list

from app.agents.llm import get_bedrock_llm

logger = logging.getLogger(__name__)

# Cache for generated questions to avoid redundant LLM calls
_question_cache: Dict[str, Dict[str, Any]] = {}


class GeneratedQuestion(BaseModel):
    """Schema for LLM-generated questions."""
    question_text: str = Field(
        description="Natural, conversational question to ask the user"
    )
    response_type: str = Field(
        description="Response type: single_choice, multi_choice, numeric, boolean, or free_text"
    )
    options: List[str] = Field(
        default_factory=list,
        description="Available options for choice-based questions (empty for free_text/numeric)"
    )
    reasoning: str = Field(
        description="Brief explanation of why this question was generated this way"
    )

    @field_validator("options", mode="before")
    @classmethod
    def parse_options(cls, v: Any) -> List[Any]:
        return parse_list(v)


def generate_question_for_attribute(
    domain: str,
    attribute_category: str,
    attribute_values: List[Dict[str, Any]],
    problem_context: Optional[str] = None,
    data_type: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Dynamically generate a question for an attribute using LLM.

    Args:
        domain: Domain name (e.g., 'brain_focus_memory')
        attribute_category: Attribute category (e.g., 'sleep_quality')
        attribute_values: List of attribute nodes with this category
        problem_context: Optional problem being addressed (e.g., 'brain_fog')
        data_type: Optional data type hint (single_choice, multi_choice, etc.)

    Returns:
        Question dictionary compatible with knowledge graph schema, or None on error

    Example:
        >>> generate_question_for_attribute(
        ...     domain="brain_focus_memory",
        ...     attribute_category="sleep_quality",
        ...     attribute_values=[
        ...         {"id": "sleep_quality_good", "value": "good"},
        ...         {"id": "sleep_quality_poor", "value": "poor"}
        ...     ],
        ...     problem_context="brain_fog"
        ... )
        {
            "id": "generated_q_sleep_quality",
            "text": "How would you describe your sleep quality?",
            "response_type": "single_choice",
            "options": ["Good", "Poor"],
            ...
        }
    """
    # Check cache first
    cache_key = f"{domain}:{attribute_category}:{problem_context or 'general'}"
    if cache_key in _question_cache:
        logger.info(
            f"Using cached generated question for {attribute_category} in {domain}"
        )
        return _question_cache[cache_key]

    logger.info(
        f"Dynamically generating question for attribute '{attribute_category}' "
        f"in domain '{domain}' (problem: {problem_context or 'N/A'})"
    )

    try:
        # Extract display-friendly values from attribute nodes
        value_options = []
        for attr in attribute_values:
            # Use display_name if available, otherwise clean up the value
            display_value = (
                attr.get('display_name') or
                attr.get('value', '').replace('_', ' ').title()
            )
            if display_value and display_value not in value_options:
                value_options.append(display_value)

        # Infer data type from attribute values if not provided
        if not data_type:
            if len(value_options) > 1:
                data_type = "single_choice"
            else:
                data_type = "free_text"

        # Build prompt for LLM
        domain_display = domain.replace('_', ' ').title()
        category_display = attribute_category.replace('_', ' ').title()

        prompt = f"""You are generating a natural, conversational question to ask a user in a {domain_display} consultation.

**Attribute Category:** {category_display}
**Available Values:** {', '.join(value_options) if value_options else 'None specified (free-text expected)'}
**Problem Context:** {problem_context or 'General consultation'}
**Expected Response Type:** {data_type}

Generate a natural question that:
1. Asks about the user's {category_display} in a friendly, conversational way
2. Explains briefly WHY this information helps (1 sentence max)
3. Is specific to the context of {problem_context or domain_display}
4. Uses simple, clear language

For choice-based questions, use the available values as options.
For free-text questions, make it open-ended but guide the user on what to provide.

Example good questions:
- "How would you describe your sleep quality? This helps me recommend the right dosage and timing."
- "What's your typical stress level like? Understanding this helps identify whether you need calming or energizing support."
- "Do you have any dietary preferences (vegetarian, vegan, etc.)? This ensures I only suggest products that fit your lifestyle."

Generate the question now."""

        # Initialize LLM with structured output and retry logic
        structured_llm = get_bedrock_llm(
            model_kwargs={"temperature": 0.3},
            structured_output_schema=GeneratedQuestion,
        )

        # Generate question
        result: GeneratedQuestion = structured_llm.invoke(prompt)

        logger.info(
            f"Generated question for {attribute_category}: '{result.question_text}' "
            f"(reasoning: {result.reasoning})"
        )

        # Convert to knowledge graph question format
        question_dict = {
            "id": f"generated_q_{attribute_category}",
            "text": result.question_text,
            "response_type": result.response_type,
            "options": result.options if result.options else value_options,
            "validation_rules": {},
            "_dynamically_generated": True,  # Mark as generated
            "_generation_reasoning": result.reasoning
        }

        # Cache the result
        _question_cache[cache_key] = question_dict

        return question_dict

    except Exception as e:
        logger.error(
            f"Failed to generate question for attribute '{attribute_category}': {e}",
            exc_info=True
        )
        return None


def clear_question_cache():
    """Clear the generated question cache. Useful for testing."""
    global _question_cache
    _question_cache.clear()
    logger.info("Cleared dynamic question cache")
