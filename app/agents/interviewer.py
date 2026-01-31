from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage
import logging

from app.config import get_settings
from app.agents.state import AgentState
from app.knowledge.query_engine import GraphQueryEngine
from app.knowledge.graph_loader import get_knowledge_graph

settings = get_settings()
logger = logging.getLogger(__name__)

# Legacy slot descriptions removed - now using knowledge graph for all slot metadata


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


def _build_graph_slot_reference(graph_questions: List[Dict[str, Any]]) -> str:
    """Build a readable reference block from knowledge graph questions."""
    lines = []
    for q in graph_questions:
        attr_category = q['attribute_category']
        reason = q.get('reason', '')
        question_text = q['question'].get('text', '')
        options = q['question'].get('options', [])

        entry = f"  - {attr_category}: {reason}"
        if question_text:
            entry += f"\n    Question: {question_text}"
        if options:
            entry += f"\n    Options: {', '.join(options)}"

        lines.append(entry)

    return "\n".join(lines)


SYSTEM_PROMPT = """\
You are a friendly, knowledgeable wellness consultant helping a user find the \
right supplement. Your job is to extract information from the user's messages \
and ask clarifying questions only when needed.

## Critical Extraction Rules:

1. **EXTRACT THOROUGHLY FIRST**: Before asking any questions, carefully extract \
   ALL values the user has explicitly or implicitly mentioned in their message. \
   - Explicit: "I prefer capsules" → format_preference: "capsule" \
   - Implicit: "I'm pregnant" → medical_constraints: ["pregnancy"] \
   - Implicit: "I'm allergic to fish" → allergies: ["fish"] \
   - Context-based: "I'm tired all the time" → may indicate severity or duration

2. **ONLY EXTRACT CLEARLY STATED VALUES**: Do NOT guess or infer beyond what's \
   clearly stated. For example: \
   - "I want protein" → DO NOT fill health_goal with a guess \
   - "skin health" → DO NOT assume "anti-aging" \
   - Only fill a slot when the user's words directly and unambiguously match it

3. **CHECK ALL SLOTS FOR EXTRACTION**: Even if a slot wasn't previously discussed, \
   extract it if the user mentions it in their message. This prevents asking about \
   information they've already provided.

4. **MAP SHORT ANSWERS TO CONTEXT**: When the user gives a short answer like \
   "capsule", "oily", "powder", map it to the correct slot based on the \
   previous question.

5. **HANDLE MULTI-CHOICE CONSTRAINTS**: For safety questions (medical_constraints, \
   allergies), extract as lists: \
   - "I'm pregnant" → medical_constraints: ["pregnancy"] \
   - "No allergies" → allergies: ["none"] \
   - "Fish and shellfish allergies" → allergies: ["fish", "shellfish"]

## After Extraction, Then Ask:

5. **IDENTIFY WHAT'S STILL MISSING**: After extraction, determine which required \
   slots are still unfilled.

6. **ASK ABOUT MISSING SLOTS ONLY**: Ask about slots that weren't extracted. \
   Include a brief reason (1-2 sentences) explaining why each piece of information \
   helps. Keep it conversational, not an interrogation.

7. **CONSIDER OPTIONAL SLOTS**: If optional slots would meaningfully improve \
   recommendations given the context, include them in your question.

8. **RESPECT USER'S PACE**: If the user says "just search", "that's enough", \
   "I don't know", or "show me what you have", set ready_to_search to true \
   and do NOT ask more questions.

9. **ALWAYS ASK WHEN SLOTS MISSING**: When required slots are still unfilled \
   after extraction, you MUST generate a question.

**DO NOT** repeat questions for slots that are already filled.

**TONE**: Get straight to the point. No filler like "Great!", "Sure!", "Awesome!".\
"""


async def interviewer_agent(state: AgentState) -> AgentState:
    """
    Manages the consultation phase: extracts information and asks clarifying questions.

    Uses knowledge graph to dynamically determine which questions to ask based on
    the identified problem and user attributes.

    The agent extracts slot values from the user's message, asks about remaining
    required (and optionally relevant) slots with brief justifications, and
    detects when the user wants to skip ahead to search.
    """
    extracted_context = state.get("extracted_context", {})
    previous_response = state.get("response")

    # --- Knowledge Graph Enhancement ---
    # Check if we have a graph-identified problem
    graph_state = extracted_context.get("graph_state", {})
    problem_id = graph_state.get("identified_problem")
    graph_domain = graph_state.get("graph_domain")

    logger.info(f"Interviewer agent called. Extracted context: {extracted_context}")
    logger.info(f"Graph state: {graph_state}, problem_id: {problem_id}, graph_domain: {graph_domain}")

    # Get graph-based questions (required for graph-first workflow)
    graph_questions = []
    required_slots = []
    optional_slots = []

    if not problem_id or not graph_domain:
        # No problem identified yet
        domain_slug = state.get("domain_slug", "")
        status = state.get("status")

        logger.info(
            f"No problem in state. domain_slug='{domain_slug}', "
            f"status='{status}', previous_response_exists={bool(previous_response)}"
        )

        # Check if we're responding to a previous question about the problem
        if status == "awaiting_slot" and previous_response:
            # User is responding to our problem question - try to extract it
            logger.info(
                f"User responding to problem identification question. "
                f"Attempting extraction from: '{state['user_message']}'"
            )

            try:
                # DYNAMIC PROBLEM CHOICE: Load all available problems from the graph
                # and ask the LLM to choose the closest match
                from langchain_aws import ChatBedrock
                from pydantic import BaseModel, Field

                # Get all available problems from the knowledge graph
                graph = get_knowledge_graph(domain_slug)
                all_problems = graph.find_nodes_by_type('problem')

                # Build a list of problem choices with their IDs and display names
                problem_choices = []
                for p in all_problems:
                    problem_id = p['id']
                    display_name = p.get('display_name', p.get('name', problem_id))
                    synonyms = p.get('synonyms', [])

                    choice_entry = f"- {problem_id}: {display_name}"
                    if synonyms:
                        choice_entry += f" (also: {', '.join(synonyms[:3])})"
                    problem_choices.append(choice_entry)

                available_problems_text = "\n".join(problem_choices)

                logger.info(f"Available problems for domain '{domain_slug}': {len(all_problems)} options")

                class ProblemSelection(BaseModel):
                    """Select the problem that best matches the user's concern."""
                    selected_problem_id: str = Field(
                        description="The ID of the problem that best matches the user's concern. "
                        "Must be one of the problem IDs from the available list."
                    )
                    reasoning: str = Field(
                        description="Brief explanation of why this problem was selected"
                    )

                extract_llm = ChatBedrock(
                    model_id=settings.bedrock_model_id,
                    region_name=settings.aws_region,
                    model_kwargs={"temperature": 0},
                )
                structured_llm = extract_llm.with_structured_output(ProblemSelection)

                selection_prompt = f"""You are helping to identify which health concern best matches what the user is asking about.

User's message: "{state['user_message']}"

Available problems in the knowledge graph:
{available_problems_text}

Select the problem ID that best matches the user's concern. You MUST choose one of the IDs from the list above.
If the user's concern could match multiple problems, choose the most specific one.
If the match is not obvious, choose the closest related problem."""

                selection_result: ProblemSelection = await structured_llm.ainvoke(selection_prompt)

                selected_problem_id = selection_result.selected_problem_id
                logger.info(
                    f"LLM selected problem '{selected_problem_id}' from available options. "
                    f"Reasoning: {selection_result.reasoning}"
                )

                # Verify the selected problem actually exists
                problem = graph.get_node(selected_problem_id)

                if problem:
                    # Successfully selected a valid problem!
                    problem_id = problem['id']
                    graph_domain = domain_slug

                    logger.info(
                        f"Interviewer selected problem '{problem_id}' "
                        f"(display: {problem.get('display_name')}) from user response"
                    )

                    # Update extracted_context with the newly identified problem
                    # Don't reassign - use existing extracted_context from line 140
                    extracted_context["graph_state"] = {
                        "identified_problem": problem_id,
                        "problem_source": "interviewer",
                        "graph_domain": graph_domain
                    }

                    # Continue with normal flow (will get questions for this problem below)
                    logger.info("Problem identified by interviewer, proceeding with slot collection")
                    # Note: problem_id and graph_domain are now set, so we'll continue to line 245+
                else:
                    # LLM selected an invalid problem ID (shouldn't happen with constrained selection)
                    logger.warning(
                        f"LLM selected invalid problem ID '{selected_problem_id}'. "
                        f"Asking user to clarify."
                    )
                    new_state = state.copy()
                    new_state["response"] = (
                        "I'm not sure I understood that. Could you be more specific about what you'd like help with? "
                        "For example, you could mention a specific concern like 'low energy', 'trouble sleeping', 'dry skin', etc."
                    )
                    new_state["status"] = "awaiting_slot"
                    new_state["next_agent"] = None
                    return new_state

            except Exception as e:
                logger.error(f"Error extracting problem: {e}", exc_info=True)
                new_state = state.copy()
                new_state["response"] = (
                    "I'm having trouble understanding. Could you describe your concern in a different way?"
                )
                new_state["status"] = "awaiting_slot"
                new_state["next_agent"] = None
                return new_state
        else:
            # First time asking about problem
            logger.info(f"No problem identified for domain '{domain_slug}'. Asking user.")
            new_state = state.copy()

            # Provide helpful suggestions based on domain
            # Try to load the graph to get example problems
            try:
                graph = get_knowledge_graph(domain_slug)
                problems = graph.find_nodes_by_type('problem')

                if problems:
                    # Get display names for first 6-8 problems as examples
                    problem_examples = []
                    for problem in problems[:8]:
                        display_name = problem.get('display_name', problem.get('name', problem['id']))
                        problem_examples.append(f"- {display_name}")

                    domain_display = graph.metadata.display_name or domain_slug.replace('_', ' ').title()
                    examples_text = "\n".join(problem_examples)

                    new_state["response"] = (
                        f"I'd love to help you with {domain_display}! To give you the best recommendations, "
                        f"could you tell me what specific concern you'd like to address? For example:\n"
                        f"{examples_text}"
                    )
                else:
                    # Fallback if no problems found
                    new_state["response"] = (
                        "I'd like to help you find the right product. "
                        "Could you tell me more specifically about what concern you'd like to address?"
                    )
            except Exception as e:
                logger.error(f"Error loading problem examples for domain '{domain_slug}': {e}")
                # Generic fallback
                new_state["response"] = (
                    "I'd like to help you find the right product. "
                    "Could you tell me more specifically about what health goal or concern you'd like to address?"
                )

            new_state["status"] = "awaiting_slot"
            new_state["next_agent"] = None
            return new_state

    # Get questions from knowledge graph
    try:
        logger.info(f"Using knowledge graph to get questions for problem '{problem_id}'")

        # STEP 1: Get global safety constraint questions (ALWAYS ask these first)
        graph = get_knowledge_graph(graph_domain)
        all_attrs = graph.find_nodes_by_type('attribute')

        safety_critical_questions = []
        for attr in all_attrs:
            if attr.get('is_global', False):
                # Find question for this attribute
                question = graph.get_question_for_attribute(attr['id'])
                if question:
                    # Check if it's safety critical
                    edges = graph.get_outgoing_edges(attr['id'], relation='ELICITS_QUESTION')
                    is_safety_critical = any(
                        edge.get('is_safety_critical', False) for edge in edges
                    )

                    # Only include safety-critical constraints (medical, allergies)
                    if is_safety_critical:
                        safety_critical_questions.append({
                            'attribute_id': attr['id'],
                            'attribute_category': attr.get('category'),
                            'priority': 0,  # Highest priority
                            'is_optional': False,
                            'is_safety_critical': is_safety_critical,
                            'reason': 'Safety screening to exclude contraindicated products',
                            'question': question
                        })

        logger.info(f"Retrieved {len(safety_critical_questions)} safety-critical constraint questions")

        # STEP 2: Get problem-specific questions
        problem_questions = GraphQueryEngine.get_interview_questions(
            domain=graph_domain,
            problem_id=problem_id
        )
        logger.info(f"Retrieved {len(problem_questions)} problem-specific questions")

        # STEP 3: Combine - safety-critical constraints FIRST, then problem-specific
        # Note: Problem-specific questions may include other global attrs like age/diet
        graph_questions = safety_critical_questions + problem_questions
        logger.info(f"Total questions: {len(graph_questions)} (safety: {len(safety_critical_questions)}, problem: {len(problem_questions)})")

        # Extract attribute categories as "slots"
        required_slots = [
            q['attribute_category']
            for q in graph_questions
            if not q.get('is_optional', False)
        ]
        optional_slots = [
            q['attribute_category']
            for q in graph_questions
            if q.get('is_optional', False)
        ]

        logger.info(f"Graph-based slots - Required: {required_slots}, Optional: {optional_slots}")

    except Exception as e:
        logger.error(f"Error getting graph questions: {e}", exc_info=True)
        # Cannot proceed without graph questions in graph-first workflow
        new_state = state.copy()
        new_state["response"] = (
            "I'm having trouble understanding your request. "
            "Could you rephrase what you're looking for?"
        )
        new_state["status"] = "awaiting_slot"
        new_state["next_agent"] = None
        return new_state

    # Identify what we still need (excluding graph_state from filled slots)
    # Check both top-level extracted_context AND graph_state.filled_attributes
    already_filled = set(k for k in extracted_context.keys() if k != "graph_state")

    # Also check filled_attributes for constraint categories
    graph_state = extracted_context.get("graph_state", {})
    filled_attrs = graph_state.get("filled_attributes", {})
    already_filled.update(filled_attrs.keys())

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

    # Build slot reference from graph questions - EXCLUDE already filled slots
    # We only want the LLM to extract from unfilled slots to avoid re-asking
    unfilled_graph_questions = [
        q for q in graph_questions
        if q['attribute_category'] not in already_filled
    ]

    slot_reference_for_extraction = _build_graph_slot_reference(unfilled_graph_questions)

    # Also build a focused reference for what we still need
    all_relevant_slots = list(dict.fromkeys(missing_required + unfilled_optional))
    relevant_graph_questions = [
        q for q in unfilled_graph_questions
        if q['attribute_category'] in all_relevant_slots
    ]
    missing_slot_reference = _build_graph_slot_reference(relevant_graph_questions)
    logger.info(f"Total slots: {len(graph_questions)}, Already filled: {len(already_filled)}, Still needed: {len(relevant_graph_questions)}")

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

    # Add graph context if available
    graph_context_note = ""
    if problem_id:
        graph_context_note = (
            f"\n**Knowledge Graph Context:**\n"
            f"  - Identified problem: {problem_id}\n"
            f"  - The questions below are dynamically generated based on what information "
            f"is most relevant for this specific problem.\n"
        )

    user_message = f"""\
Domain: {state.get('domain_slug')}
{graph_context_note}
Information already collected:
{filled_summary}

## ALL AVAILABLE SLOTS (for extraction reference):
{slot_reference_for_extraction}

## PRIORITY: Extract First, Then Ask

STEP 1: Extract any values from the user's message that match ANY of the slots above.
- Look for explicit mentions (e.g., "I prefer capsules" → format_preference: "capsule")
- Look for implicit information (e.g., "I'm pregnant" → life_stage or dietary_restrictions)
- Extract from the CURRENT message, even if it was used for problem identification

STEP 2: After extraction, identify what's still missing:
Required slots still needed: {missing_required or '(all filled)'}
Optional slots available: {unfilled_optional or '(none)'}

## SLOTS WE STILL NEED (ask about these if not extracted):
{missing_slot_reference}
{previous_question_section}{first_pass_note}
User's latest message: "{state['user_message']}"

Respond with:
1. extracted_values: ALL values you can extract from the user's message (not just what we're asking about)
2. missing_slots: What's still missing AFTER extraction
3. question: Ask about missing slots (if any remain)
"""

    model = get_interviewer_model()
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]
    result: InterviewerResponse = await model.ainvoke(messages)

    # --- Update state ---
    new_state = state.copy()

    # Merge extracted values while preserving graph_state
    updated_context = {**extracted_context, **result.extracted_values}

    # Store filled attributes with their graph metadata
    if result.extracted_values:
        if "graph_state" not in updated_context:
            updated_context["graph_state"] = graph_state.copy()

        # Track filled attributes with their graph metadata
        if "filled_attributes" not in updated_context["graph_state"]:
            updated_context["graph_state"]["filled_attributes"] = {}

        for attr_category, value in result.extracted_values.items():
            # Find the corresponding graph question to get attribute metadata
            matching_question = next(
                (q for q in graph_questions if q['attribute_category'] == attr_category),
                None
            )

            if matching_question:
                # IMPORTANT: Map user's answer to the correct attribute ID
                # The matching_question['attribute_id'] is just a template attribute
                # We need to find the actual attribute node that matches the user's value
                try:
                    graph = get_knowledge_graph(graph_domain)
                    all_attrs = graph.find_nodes_by_type('attribute')

                    # Find attribute with matching category and value
                    correct_attr_id = None
                    value_lower = str(value).lower().strip()

                    for attr in all_attrs:
                        if attr.get('category') == attr_category:
                            attr_value = str(attr.get('value', '')).lower().strip()

                            # Try exact match
                            if attr_value == value_lower:
                                correct_attr_id = attr['id']
                                break

                            # Try matching display name or name
                            attr_display = attr.get('display_name', '').lower().strip()
                            attr_name = attr.get('name', '').lower().strip()

                            if attr_display == value_lower or attr_name == value_lower:
                                correct_attr_id = attr['id']
                                break

                    # Fallback: if no match found, log warning and use template ID
                    if not correct_attr_id:
                        logger.warning(
                            f"Could not find attribute ID for category '{attr_category}' "
                            f"with value '{value}'. Using template ID as fallback."
                        )
                        correct_attr_id = matching_question['attribute_id']

                    updated_context["graph_state"]["filled_attributes"][attr_category] = {
                        "value": value,
                        "attribute_id": correct_attr_id,
                        "priority": matching_question['priority']
                    }

                except Exception as e:
                    logger.error(f"Error mapping attribute value to ID: {e}", exc_info=True)
                    # Fallback to template ID
                    updated_context["graph_state"]["filled_attributes"][attr_category] = {
                        "value": value,
                        "attribute_id": matching_question['attribute_id'],
                        "priority": matching_question['priority']
                    }

    new_state["extracted_context"] = updated_context
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
