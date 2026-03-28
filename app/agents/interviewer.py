from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
from langchain_core.messages import HumanMessage, SystemMessage
import logging

from app.agents.validators import parse_dict, parse_list, parse_bool

from app.config import get_settings
from app.agents.state import AgentState
from app.agents.llm import get_bedrock_llm
from app.knowledge.query_engine import GraphQueryEngine
from app.knowledge.graph_loader import get_knowledge_graph

settings = get_settings()
logger = logging.getLogger(__name__)

# Legacy slot descriptions removed - now using knowledge graph for all slot metadata


class InterviewerResponse(BaseModel):
    """Structured response from the Interviewer agent."""
    reasoning: str = Field(
        default="",
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
    suggested_replies: List[str] = Field(
        default_factory=list,
        description=(
            "2-6 short reply options the user can tap to answer quickly. "
            "Base these on the question you're asking. For yes/no questions use "
            "['Yes', 'No', 'Prefer not to say']. For choice questions use the "
            "available options. Keep labels short (1-4 words each)."
        ),
    )

    @field_validator("extracted_values", mode="before")
    @classmethod
    def parse_extracted_values(cls, v: Any) -> Dict[str, Any]:
        return parse_dict(v)

    @field_validator("missing_slots", "suggested_optional_slots", "suggested_replies", mode="before")
    @classmethod
    def parse_list_fields(cls, v: Any) -> List[Any]:
        v = parse_list(v)
        if isinstance(v, list):
            return [item for item in v if item is not None]
        return v

    @field_validator("ready_to_search", mode="before")
    @classmethod
    def parse_ready_to_search(cls, v: Any) -> bool:
        return parse_bool(v)


def get_interviewer_model():
    """Initialize the Bedrock model for interviewing."""
    return get_bedrock_llm(structured_output_schema=InterviewerResponse)


def _cat_str(cat) -> str:
    """Return the canonical string for an attribute/constraint category.

    Knowledge-graph constraint types are ConstraintType enum instances
    (e.g. ConstraintType.ALLERGY with value "allergy").  Using str() on
    them produces the ugly "<ConstraintType.ALLERGY: 'allergy'>" repr.
    This helper always returns the clean lowercase value string.
    """
    if hasattr(cat, 'value'):
        return str(cat.value).lower()
    return str(cat).lower()


def _slot_is_filled(slot_cat, already_filled: set) -> bool:
    """Check if a slot category is covered by already_filled.

    The LLM extracts slot values using natural plural / compound names
    (e.g. "allergies", "dietary_preference") while knowledge-graph
    constraint types use singular lowercase values ("allergy", "dietary").
    This helper normalises both sides so the comparison is robust.
    """
    slot_str = _cat_str(slot_cat)
    for key in already_filled:
        key_str = str(key).lower()
        if key_str == slot_str:
            return True
        # "allergies" covers "allergy", "diets" covers "diet"
        if key_str.rstrip('s') == slot_str.rstrip('s') and len(slot_str) > 2:
            return True
        # "dietary_preference" covers "dietary"; "diet_type" covers "diet"
        if key_str.startswith(slot_str) or slot_str.startswith(key_str):
            return True
    return False


def _build_graph_slot_reference(graph_questions: List[Dict[str, Any]]) -> str:
    """Build a readable reference block from knowledge graph questions."""
    lines = []
    for q in graph_questions:
        attr_category = _cat_str(q['attribute_category'])  # clean string, no enum repr
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


def _compute_search_impact(
    graph,
    problem_id: str,
    question: Dict[str, Any],
) -> float:
    """Score a question by how much its attribute/constraint affects search results.

    The score combines:
    - RECOMMENDED_FOR edge count: how many treating ingredients have
      RECOMMENDED_FOR edges pointing to attributes in this category.
    - CONTRAINDICATED_FOR edge count: how many treating ingredients have
      CONTRAINDICATED_FOR edges pointing to constraints in this category.
      Knowing constraints helps filter out dangerous products.
    - Hard-filter bonus: attribute categories that create SQL filters
      (diet, allergies) get a flat bonus.
    """
    attr_category = question['attribute_category']

    # 1. Count RECOMMENDED_FOR edges from treating ingredients to this category
    treating_ingredients = graph.get_treating_ingredients(problem_id, min_efficacy=0.5)
    all_attrs = graph.find_nodes_by_type('attribute')
    category_attr_ids = {a['id'] for a in all_attrs if a.get('category') == attr_category}

    recommendation_count = 0
    for ing in treating_ingredients:
        for attr_id in category_attr_ids:
            recs = graph.get_recommended_ingredients_for_attribute(attr_id, min_strength=0.0)
            if any(r['id'] == ing['id'] for r in recs):
                recommendation_count += 1

    # 2. Count CONTRAINDICATED_FOR edges from treating ingredients to constraints
    #    in this category. Knowing about allergies/diet helps filter out unsafe products.
    all_constraints = graph.find_nodes_by_type('constraint')
    category_constraint_ids = {c['id'] for c in all_constraints if c.get('type') == attr_category}

    contraindication_count = 0
    for ing in treating_ingredients:
        edges = graph.get_outgoing_edges(ing['id'], relation='CONTRAINDICATED_FOR')
        for edge in edges:
            if edge['target'] in category_constraint_ids:
                contraindication_count += 1

    # 3. Hard filter bonus for diet/allergies
    hard_filter_categories = {'diet', 'dietary_preference', 'allergies', 'allergy', 'dietary'}
    hard_filter_bonus = 5.0 if attr_category in hard_filter_categories else 0.0

    return recommendation_count + contraindication_count + hard_filter_bonus


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

6. **ASK ONE QUESTION AT A TIME**: Ask about only ONE missing slot per turn. \
   Pick the highest-priority missing slot and ask a single, focused question. \
   Include a brief reason (1 sentence) explaining why this information helps. \
   Do NOT bundle multiple slots into one question — keep it conversational, \
   not an interrogation.

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

    # Auto-promote candidate_problem from the router when confidence is high.
    # The router already validated the problem against the knowledge graph.
    # - High confidence (>= 0.85): auto-promote, no need to re-ask
    # - Lower confidence: ask a targeted confirmation question instead of
    #   a full problem re-selection list
    candidate = extracted_context.get("candidate_problem")
    if not problem_id and candidate:
        confidence = candidate.get("confidence", 0)
        if confidence >= 0.85:
            problem_id = candidate["problem_id"]
            graph_domain = candidate["graph_domain"]
            extracted_context["graph_state"] = {
                **graph_state,
                "identified_problem": problem_id,
                "problem_source": "router",
                "graph_domain": graph_domain,
            }
            extracted_context.pop("candidate_problem", None)
            logger.info(
                f"Auto-promoted candidate_problem '{problem_id}' from router "
                f"(confidence={confidence:.2f}) to identified_problem"
            )

            # Route to initial_products so the user sees relevant products
            # while we continue with slot collection.
            new_state = state.copy()
            new_state["extracted_context"] = extracted_context
            new_state["status"] = "collecting_info"
            new_state["next_agent"] = "initial_products"
            return new_state
        else:
            logger.info(
                f"Candidate problem '{candidate['problem_id']}' has low confidence "
                f"({confidence:.2f}), will ask user to confirm"
            )

    logger.info(f"Interviewer agent called. Extracted context: {extracted_context}")
    logger.info(f"Graph state: {graph_state}, problem_id: {problem_id}, graph_domain: {graph_domain}")

    # --- Direct product personalization mode ---
    # If the user did a direct product search and wants to personalise,
    # skip problem identification and ask only global safety questions.
    direct_search_term = extracted_context.get("direct_search_term")
    if direct_search_term and not problem_id:
        domain_slug = state.get("domain_slug", "")
        logger.info(
            f"Direct product mode: direct_search_term='{direct_search_term}', "
            f"domain_slug='{domain_slug}'"
        )

        try:
            # Search tenant-enabled knowledge graphs for global safety questions,
            # since the user's domain may not define them (e.g., sleep_stress
            # has no global attrs but energy/gut/hair do).
            from app.knowledge.graph_loader import list_available_graphs
            available_graphs = list_available_graphs()
            tenant_enabled = state.get("tenant_enabled_domains")
            if tenant_enabled and "*" not in tenant_enabled:
                available_graphs = [g for g in available_graphs if g in tenant_enabled]

            # Prioritize the current domain's graph
            graph_order = sorted(
                available_graphs,
                key=lambda g: (0 if g == domain_slug else 1)
            )

            global_questions: list[dict] = []
            seen_categories: set = set()

            for graph_name in graph_order:
                try:
                    graph = get_knowledge_graph(graph_name)
                    all_attrs = graph.find_nodes_by_type('attribute')

                    for attr in all_attrs:
                        if attr.get('is_global', False):
                            attr_category = attr.get('category')
                            if attr_category in seen_categories:
                                continue

                            question = graph.get_question_for_attribute(attr['id'])
                            if question:
                                seen_categories.add(attr_category)

                                edges = graph.get_outgoing_edges(attr['id'], relation='ELICITS_QUESTION')
                                is_safety_critical = any(
                                    edge.get('is_safety_critical', False) for edge in edges
                                )
                                attr_edge_priority = min(
                                    (edge.get('priority', 99) for edge in edges), default=99
                                )
                                global_questions.append({
                                    'attribute_id': attr['id'],
                                    'attribute_category': attr_category,
                                    'priority': attr_edge_priority,
                                    'is_optional': False,
                                    'is_safety_critical': is_safety_critical,
                                    'reason': 'Safety screening',
                                    'question': question,
                                })
                except Exception as e:
                    logger.warning(f"Error loading global attrs from graph '{graph_name}': {e}")
                    continue

            if global_questions:
                logger.info(
                    f"Direct product mode: {len(global_questions)} global safety questions available"
                )
                # Check which are already filled
                filled_attrs = graph_state.get("filled_attributes", {})
                already_filled = set(k for k in extracted_context.keys() if k != "graph_state")
                already_filled.update(filled_attrs.keys())

                unfilled = [q for q in global_questions if not _slot_is_filled(q['attribute_category'], already_filled)]

                # Cap at 3 questions
                questions_asked = graph_state.get("questions_asked", 0)
                MAX_SAFETY_QUESTIONS = 3

                if not unfilled or questions_asked >= MAX_SAFETY_QUESTIONS:
                    # All safety questions answered (or limit reached) — proceed to search
                    logger.info("Direct product mode: safety questions done, routing to search")
                    new_state = state.copy()
                    new_state["next_agent"] = "search"
                    new_state["status"] = "collecting_info"
                    return new_state

                # Use the normal interviewer LLM to ask the next safety question
                # by falling through to the slot-filling logic below with
                # these global questions as the graph_questions.
                # We set graph_questions/required_slots so the rest of the
                # function works seamlessly.
                graph_questions = unfilled
                required_slots = [q['attribute_category'] for q in unfilled]
                optional_slots = []

                # Skip the "no problem identified" block and the normal
                # graph question loading — jump directly to the slot-filling
                # logic below (line ~545 in the original).
                # We'll use a flag to signal this.
                _direct_product_safety_mode = True
            else:
                # No safety questions available — proceed to search directly
                logger.info("Direct product mode: no global safety questions, routing to search")
                new_state = state.copy()
                new_state["next_agent"] = "search"
                new_state["status"] = "collecting_info"
                return new_state

        except Exception as e:
            logger.warning(f"Direct product mode: error loading safety questions: {e}")
            # No safety questions available — proceed to search directly
            new_state = state.copy()
            new_state["next_agent"] = "search"
            new_state["status"] = "collecting_info"
            return new_state
    else:
        _direct_product_safety_mode = False

    # Get graph-based questions (required for graph-first workflow)
    if not _direct_product_safety_mode:
        graph_questions = []
        required_slots = []
        optional_slots = []

    if not _direct_product_safety_mode and (not problem_id or not graph_domain):
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
                        default="",
                        description="Brief explanation of why this problem was selected"
                    )

                structured_llm = get_bedrock_llm(structured_output_schema=ProblemSelection)

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

                    # Route to initial_products first so the user sees
                    # relevant products while we continue slot collection.
                    logger.info("Problem identified by interviewer, fetching initial products before slot collection")
                    new_state = state.copy()
                    new_state["extracted_context"] = extracted_context
                    new_state["status"] = "collecting_info"
                    new_state["next_agent"] = "initial_products"
                    return new_state
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

            # If the router detected a low-confidence candidate, ask a
            # targeted confirmation instead of showing the full list.
            candidate = extracted_context.get("candidate_problem")
            if candidate:
                try:
                    graph = get_knowledge_graph(domain_slug)
                    candidate_node = graph.get_node(candidate["problem_id"])
                    candidate_display = (
                        candidate_node.get("display_name", candidate_node.get("name", candidate["problem_id"]))
                        if candidate_node else candidate["problem_id"].replace("_", " ").title()
                    )

                    # Get a few alternative problems for the suggested replies
                    all_problems = graph.find_nodes_by_type("problem")
                    alt_names = [
                        p.get("display_name", p.get("name", p["id"]))
                        for p in all_problems
                        if p["id"] != candidate["problem_id"]
                    ][:3]

                    new_state["response"] = (
                        f"It sounds like you're concerned about **{candidate_display}** — is that right, "
                        f"or did you have something else in mind?"
                    )
                    new_state["suggested_replies"] = [
                        f"Yes, {candidate_display}",
                        *alt_names,
                        "Something else",
                    ]
                except Exception as e:
                    logger.warning(f"Error building confirmation for candidate: {e}")
                    # Fall through to the normal full-list path below
                    candidate = None

            if not candidate:
                # No candidate — ask conversationally without listing problems.
                new_state["response"] = (
                    "To give you the best recommendations, could you tell me "
                    "what specific concern you'd like to address?"
                )

            new_state["status"] = "awaiting_slot"
            new_state["next_agent"] = None
            return new_state

    # Get questions from knowledge graph (skip if already loaded in direct product mode)
    if not _direct_product_safety_mode:
        try:
            logger.info(f"Using knowledge graph to get questions for problem '{problem_id}'")

            # STEP 1: Collect ALL questions into one pool
            graph = get_knowledge_graph(graph_domain)
            all_attrs = graph.find_nodes_by_type('attribute')

            all_questions: List[Dict[str, Any]] = []

            # Problem-specific questions
            problem_questions = GraphQueryEngine.get_interview_questions(
                domain=graph_domain,
                problem_id=problem_id
            )
            all_questions.extend(problem_questions)
            logger.info(f"Retrieved {len(problem_questions)} problem-specific questions")

            # Global safety questions (collected but NOT force-prepended)
            existing_categories = {q['attribute_category'] for q in all_questions}
            safety_count = 0
            for attr in all_attrs:
                if attr.get('is_global', False):
                    question = graph.get_question_for_attribute(attr['id'])
                    if question:
                        attr_category = attr.get('category')
                        # Skip if already covered by problem-specific questions
                        if attr_category in existing_categories:
                            continue
                        edges = graph.get_outgoing_edges(attr['id'], relation='ELICITS_QUESTION')
                        is_safety_critical = any(
                            edge.get('is_safety_critical', False) for edge in edges
                        )
                        # Get priority from edges if available
                        attr_edge_priority = min(
                            (edge.get('priority', 99) for edge in edges), default=99
                        )
                        all_questions.append({
                            'attribute_id': attr['id'],
                            'attribute_category': attr_category,
                            'priority': attr_edge_priority,
                            'is_optional': False,
                            'is_safety_critical': is_safety_critical,
                            'reason': 'Safety screening',
                            'question': question
                        })
                        existing_categories.add(attr_category)
                        safety_count += 1

            logger.info(f"Retrieved {safety_count} global safety questions")

            # Constraint-based safety questions (allergies, dietary restrictions)
            # Constraints are a separate node type from attributes and need
            # their own scan to enter the question pool.
            # Track question IDs already in the pool to avoid duplicate questions
            # (e.g., attribute with category "allergies" and constraint with
            # type "allergy" may both point to the same q_allergies question).
            existing_question_ids = {
                q['question'].get('id') for q in all_questions if q.get('question')
            }
            all_constraints = graph.find_nodes_by_type('constraint')
            constraint_count = 0
            for constraint in all_constraints:
                constraint_type = constraint.get('type')  # e.g., 'allergy', 'dietary'
                # Skip if this constraint type is already covered
                if constraint_type in existing_categories:
                    continue
                # Check if this constraint has an ELICITS_QUESTION edge
                edges = graph.get_outgoing_edges(constraint['id'], relation='ELICITS_QUESTION')
                if not edges:
                    continue
                edge = edges[0]
                question_id = edge['target']
                # Skip if this question is already in the pool via an attribute
                if question_id in existing_question_ids:
                    continue
                question_node = graph.get_node(question_id)
                if not question_node:
                    continue
                is_safety_critical = any(
                    e.get('is_safety_critical', False) for e in edges
                )
                edge_priority = min(
                    (e.get('priority', 99) for e in edges), default=99
                )
                question = {
                    **question_node,
                    'condition': edge.get('condition', 'always'),
                    'timing': edge.get('timing', 'immediate')
                }
                all_questions.append({
                    'attribute_id': constraint['id'],
                    'attribute_category': constraint_type,
                    'priority': edge_priority,
                    'is_optional': False,
                    'is_safety_critical': is_safety_critical,
                    'reason': 'Safety screening — constraint',
                    'question': question
                })
                existing_categories.add(constraint_type)
                existing_question_ids.add(question_id)
                constraint_count += 1

            logger.info(f"Retrieved {constraint_count} constraint safety questions")

            # STEP 2: Deduplicate by attribute_category (keep first occurrence)
            seen_categories: set = set()
            deduped: List[Dict[str, Any]] = []
            for q in all_questions:
                if q['attribute_category'] not in seen_categories:
                    seen_categories.add(q['attribute_category'])
                    deduped.append(q)

            # STEP 3: Score and sort by search impact (highest first)
            for q in deduped:
                q['search_impact'] = _compute_search_impact(graph, problem_id, q)
            deduped.sort(key=lambda x: x['search_impact'], reverse=True)
            deduped = [q for q in deduped if q['search_impact'] > 0 or q.get('is_safety_critical', False)]

            graph_questions = deduped
            logger.info(
                f"Total questions after dedup: {len(graph_questions)}, "
                f"search_impact scores: {[(q['attribute_category'], q['search_impact']) for q in graph_questions]}"
            )

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

    missing_required = [s for s in required_slots if not _slot_is_filled(s, already_filled)]
    unfilled_optional = [s for s in optional_slots if not _slot_is_filled(s, already_filled)]

    # Cap personalisation questions at 3 — proceed to search after that
    MAX_PERSONALISATION_QUESTIONS = 3
    questions_asked = graph_state.get("questions_asked", 0)

    if questions_asked >= MAX_PERSONALISATION_QUESTIONS:
        logger.info(
            f"Reached question limit ({questions_asked}/{MAX_PERSONALISATION_QUESTIONS}), "
            f"proceeding to search with collected info"
        )
        new_state = state.copy()
        new_state["next_agent"] = "search"
        new_state["status"] = "collecting_info"
        return new_state

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
        if not _slot_is_filled(q['attribute_category'], already_filled)
    ]

    slot_reference_for_extraction = _build_graph_slot_reference(unfilled_graph_questions)

    # Build a focused reference for what we still need.
    # Limit to just the NEXT question to ask (the top-ranked unfilled slot by
    # search_impact) so the LLM doesn't pick a lower-impact slot instead.
    remaining_budget = MAX_PERSONALISATION_QUESTIONS - questions_asked
    all_relevant_slots = list(dict.fromkeys(missing_required + unfilled_optional))
    relevant_graph_questions = [
        q for q in unfilled_graph_questions
        if any(_slot_is_filled(q['attribute_category'], {s}) for s in all_relevant_slots)
    ][:remaining_budget]
    missing_slot_reference = _build_graph_slot_reference(relevant_graph_questions)
    logger.info(f"Total slots: {len(graph_questions)}, Already filled: {len(already_filled)}, Still needed: {len(relevant_graph_questions)}")

    # Previous question context for short-answer mapping.
    # Use the stored pending_slot_question rather than state["response"] so
    # that the context survives an ingredient_info detour (which overwrites
    # state["response"] with the ingredient explanation).
    pending_slot_q = extracted_context.get("pending_slot_question")
    previous_question_section = ""
    if pending_slot_q:
        previous_question_section = (
            f'\nPrevious question you asked the user:\n  "{pending_slot_q}"\n'
            "The user's message below is likely answering this question.\n"
        )

    filled_summary = (
        "\n".join(f"  - {k}: {v}" for k, v in extracted_context.items())
        if extracted_context
        else "  (none yet)"
    )

    first_pass_note = ""

    # Add graph context if available
    graph_context_note = ""
    if problem_id:
        graph_context_note = (
            f"\n**Knowledge Graph Context:**\n"
            f"  - Identified problem: {problem_id}\n"
            f"  - The questions below are dynamically generated based on what information "
            f"is most relevant for this specific problem.\n"
        )
    elif _direct_product_safety_mode:
        graph_context_note = (
            f"\n**Direct Product Mode:**\n"
            f"  - The user asked for '{direct_search_term}' directly.\n"
            f"  - We are only asking safety screening questions (allergies, pregnancy, diet).\n"
            f"  - Do NOT ask about their health problem or concern — they already know what they want.\n"
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

## SLOTS WE STILL NEED (for extraction reference — ask about only ONE per turn):
{missing_slot_reference}
{previous_question_section}{first_pass_note}
## SUGGESTED REPLY OPTIONS
Include suggested_replies in your response — short labels the user can tap.
Use the options from the graph questions above when applicable.
For yes/no questions use ['Yes', 'No', 'Prefer not to say'].
For choice questions use the available options from the slot definitions.
Keep labels short (1-4 words each), max 6 options.

User's latest message: "{state['user_message']}"

Respond with:
1. extracted_values: ALL values you can extract from the user's message (not just what we're asking about)
2. missing_slots: What's still missing AFTER extraction
3. question: Ask about ONE missing slot only — pick the highest priority one
4. suggested_replies: Short tap-able reply options matching your single question
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
                (q for q in graph_questions if _slot_is_filled(q['attribute_category'], {attr_category})),
                None
            )

            if matching_question:
                # IMPORTANT: Map user's answer to the correct attribute ID
                # The matching_question['attribute_id'] is just a template attribute
                # We need to find the actual attribute node that matches the user's value
                try:
                    effective_domain = graph_domain or state.get("domain_slug", "")
                    graph = get_knowledge_graph(effective_domain)
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
    new_state["suggested_replies"] = result.suggested_replies

    # Determine whether to continue asking or proceed to search.
    # We only keep asking if the LLM actually produced a question.
    # If it suggested optional slots but didn't write a question, just search.
    has_question = bool(result.question and result.question.strip())
    should_search = (
        result.ready_to_search
        or not has_question
    )

    if is_first_pass:
        # Show initial products with an option to personalise.
        domain_name = (state.get("domain_slug") or "this category").replace("_", " ").title()
        personalise_prompt = "Would you like me to personalise these recommendations for you?"
        new_state["response"] = (
            f"### {domain_name} — Top Picks for You\n\n"
            "Here are some recommendations based on your concern.\n\n"
            "---\n\n"
            "Want better results? I can personalise these recommendations "
            "by asking a few quick questions."
        )
        new_state["status"] = "awaiting_slot"
        new_state["suggested_replies"] = ["Personalise for me"]
        new_state["next_agent"] = None
        # Store the pending interaction so the router has context on the next
        # turn — without this, messages like "yes, personalise it" look like
        # a new out-of-scope query.
        updated_context["pending_slot_question"] = personalise_prompt
        new_state["extracted_context"] = updated_context
        return new_state

    if should_search:
        new_state["response"] = None
        new_state["status"] = "collecting_info"
        new_state["next_agent"] = "search"
        new_state["optional_slot_hint"] = None
        # Clear the pending slot question — interview is done
        updated_context.pop("pending_slot_question", None)
        new_state["extracted_context"] = updated_context
    else:
        question_text = result.question  # guaranteed non-empty here
        new_state["response"] = question_text
        new_state["status"] = "awaiting_slot"
        new_state["next_agent"] = None  # End turn — wait for user input

        # Persist the slot question so it survives any ingredient_info detour
        updated_context["pending_slot_question"] = question_text

        # Increment question counter
        current_count = updated_context.get("graph_state", {}).get("questions_asked", 0)
        if "graph_state" not in updated_context:
            updated_context["graph_state"] = {}
        updated_context["graph_state"]["questions_asked"] = current_count + 1
        new_state["extracted_context"] = updated_context

    return new_state
