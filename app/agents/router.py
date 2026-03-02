from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.config import get_settings
from app.agents.state import AgentState
from app.agents.llm import get_bedrock_llm
from app.knowledge.query_engine import GraphQueryEngine
from app.knowledge.graph_loader import list_available_graphs, get_all_active_domains, get_knowledge_graph

settings = get_settings()
logger = logging.getLogger(__name__)

class RouterResponse(BaseModel):
    """Structured response from the Router agent."""
    domain_slug: str = Field(description="The slug of the identified domain or 'out_of_scope'")
    intent_type: str = Field(
        description=(
            "Type of intent: "
            "'query' for specific product search, "
            "'journey' for customer journey bundle, "
            "'direct_product' for explicit product/ingredient purchase requests, "
            "'ingredient_info' for educational questions about how an ingredient or supplement works, "
            "'filter' for budget/format/dietary filter requests on already-shown products "
            "(e.g. 'Under ₹1000', 'Vegan options', 'Capsule form', 'Without fish')"
        )
    )
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")
    reasoning: str = Field(default="", description="Brief explanation for the classification")
    extracted_problem: Optional[str] = Field(
        default=None,
        description="Extracted problem or health goal from user message if clearly stated (e.g., 'low energy', 'poor sleep'). Leave null if unclear - the interviewer will ask."
    )
    direct_search_term: Optional[str] = Field(
        default=None,
        description="The specific product or ingredient name the user asked for. Only set when intent_type is 'direct_product'."
    )
    inline_constraints: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Budget/dietary/format constraints found inline in the same message as a direct_product or filter request. "
            "Use these exact keys: "
            "'budget_max' (number, strip currency symbol — e.g. 1000 for 'under ₹1000' or 50 for 'under $50'), "
            "'dietary_preference' (string — e.g. 'vegan'), "
            "'format_preference' (string — e.g. 'capsule'). "
            "Examples: 'collagen under ₹1000' → {budget_max: 1000}, "
            "'vegan protein powder' → {dietary_preference: 'vegan'}. "
            "Leave null if no constraints are mentioned."
        )
    )

def get_router_model():
    """Initialize the Bedrock model for routing."""
    return get_bedrock_llm(structured_output_schema=RouterResponse)


def _filter_domains_for_tenant(domains: list[dict], tenant_enabled: list[str] | None) -> list[dict]:
    """Filter domains by tenant's enabled_domains list. '*' means all."""
    if not tenant_enabled or "*" in tenant_enabled:
        return domains
    return [d for d in domains if d["domain"] in tenant_enabled]


def _build_dynamic_problem_reference(tenant_enabled_domains: list[str] | None = None) -> str:
    """
    Build a dynamic problem reference by loading all active knowledge graphs
    and extracting their problems with synonyms.

    Returns:
        Formatted string with problem categories and examples for the router prompt
    """
    domains = get_all_active_domains()
    domains = _filter_domains_for_tenant(domains, tenant_enabled_domains)
    problem_sections = []

    for domain in domains:
        try:
            # Load the knowledge graph for this domain
            graph = get_knowledge_graph(domain['domain'])

            # Get all problems from this graph
            problems = graph.find_nodes_by_type('problem')

            if not problems:
                continue

            # Build problem section for this domain
            problem_lines = []
            for problem in problems:
                # Get the canonical name and display name
                problem_name = problem.get('name', problem['id'])

                # Get first 3-4 synonyms for examples
                synonyms = problem.get('synonyms', [])
                synonym_examples = ', '.join(synonyms[:4]) if synonyms else ''

                if synonym_examples:
                    problem_lines.append(f'- "{problem_name}" ({synonym_examples})')
                else:
                    problem_lines.append(f'- "{problem_name}"')

            # Add section header with domain name
            section_header = f"**{domain['display_name']} Problems:**"
            problem_sections.append(section_header)
            problem_sections.extend(problem_lines)
            problem_sections.append("")  # Empty line between sections

        except Exception as e:
            logger.warning(f"Error loading problems from domain '{domain['domain']}': {e}")
            continue

    if not problem_sections:
        # Fallback if no graphs are available
        return """**No knowledge graphs available.**
Please ensure knowledge graphs are properly configured in app/knowledge/graphs/"""

    return "\n".join(problem_sections)



async def router_agent(state: AgentState, db: AsyncSession) -> AgentState:
    """
    Classifies the user's message into a domain and optionally extracts the problem.

    The router focuses on domain identification. If the specific problem is clear,
    it will extract it. If not, the interviewer will ask about it.
    """
    # Load domains from knowledge graphs, filtered by tenant's enabled domains
    tenant_enabled = state.get("tenant_enabled_domains")
    domains = get_all_active_domains()
    domains = _filter_domains_for_tenant(domains, tenant_enabled)

    # Format domain descriptions for the prompt
    domain_descriptions = "\n".join([
        f"- {d['domain']}: {d['display_name']}. Use this for: {d.get('persona', 'General requests')}"
        for d in domains
    ])

    # Dynamically build problem reference from all knowledge graphs
    problem_reference = _build_dynamic_problem_reference(tenant_enabled)

    system_prompt = f"""You are a specialized Triage Agent for CurateAI. Your job is to identify the domain and optionally extract the problem if clearly stated.

Available Domains:
{domain_descriptions}
- out_of_scope: Use this for requests that are not related to wellness, supplements, health goals, or any of the domains listed above (e.g., small talk, weather, politics).

Intent Types:
1. **journey**: The user is starting a new activity, phase, or routine and needs a comprehensive set of products for that journey.
   - Keywords: "starting", "new to", "beginner", "getting into", "beginning", "first time", "just started"
   - Examples: "I'm starting gym", "new to skincare", "beginning my fitness journey", "getting into running"

2. **query**: The user has a specific need, problem, or symptom and needs help finding the right product.
   - Examples: "I'm so tired all the time", "looking for moisturizer for dry skin", "I can't sleep well"

3. **direct_product**: The user explicitly asks for a specific product or ingredient BY NAME to purchase or see. They already know what they want — no interview needed.
   - The user names a specific supplement, ingredient, or product type
   - Examples: "I want melatonin" → direct_search_term: "melatonin"
   - "show me vitamin C" → direct_search_term: "vitamin C"
   - "do you have collagen?" → direct_search_term: "collagen"
   - "I need iron supplements" → direct_search_term: "iron"
   - "looking for magnesium" → direct_search_term: "magnesium"
   - IMPORTANT: Only use direct_product for explicit product/ingredient names, NOT for symptoms or problems.
     - "I'm tired" → query (symptom, not a product name)
     - "I need help with sleep" → query (problem, not a product name)
     - "I want melatonin" → direct_product (melatonin is an ingredient name)
     - "show me protein powder" → direct_product (protein powder is a product type)

4. **ingredient_info**: The user is asking an EDUCATIONAL question about how an ingredient or supplement works. They want to learn, not necessarily buy.
   - Key signals: "how does X work", "why should I use/take X", "what does X do", "tell me about X", "explain X", "benefits of X", "what is X", "how does it work"
   - Examples:
     - "How does collagen work?" → ingredient_info
     - "Why should I use vitamin C?" → ingredient_info
     - "What does magnesium do for sleep?" → ingredient_info
     - "Tell me about hyaluronic acid" → ingredient_info
     - "Benefits of zinc for skin" → ingredient_info
     - "Explain how collagen helps skin" → ingredient_info
   - IMPORTANT: Distinguish from direct_product:
     - "How does collagen work?" → ingredient_info (wants explanation)
     - "Show me collagen products" → direct_product (wants to buy)
     - "Do you have collagen?" → direct_product (wants to buy)
     - "Why should I use collagen?" → ingredient_info (wants explanation)
   - For ingredient_info, set domain_slug to the most relevant domain if determinable, otherwise 'wellness'.

Available Problems by Domain (for reference only):

{problem_reference}

## Your Task:

1. **Identify the domain** - This is required. Determine which domain the user's request belongs to.
2. **Extract problem if clear** - If the user explicitly mentions a specific problem from the lists above, extract it. If vague or unclear, leave it null - the interviewer will ask.
3. **Determine intent type** - Is this a journey (starting something new) or query (specific need)?
4. **Set confidence** - How confident are you in the domain classification?

**Important**: Do NOT try to force a problem extraction if the user's request is vague. It's okay to leave extracted_problem as null. The interviewer will handle problem identification in those cases.

**Examples:**

Example 1 - Specific problem stated:
User: "I'm so tired all the time"
→ domain_slug: "wellness", extracted_problem: "low_energy", intent_type: "query", confidence: 0.95

Example 2 - Vague request (no problem extraction):
User: "I want to feel better"
→ domain_slug: "wellness", extracted_problem: null, intent_type: "query", confidence: 0.7

Example 3 - Domain clear, no specific problem:
User: "Help with my skin"
→ domain_slug: "skin_health", extracted_problem: null, intent_type: "query", confidence: 0.8

Example 4 - Specific skin concern:
User: "My skin looks dull and tired"
→ domain_slug: "skin_health", extracted_problem: "dull_skin", intent_type: "query", confidence: 0.9

Example 5 - Journey intent:
User: "I'm starting a new gym routine"
→ domain_slug: "wellness", extracted_problem: null, intent_type: "journey", confidence: 0.95

Example 6 - Direct product request:
User: "I want melatonin"
→ domain_slug: "wellness", extracted_problem: null, intent_type: "direct_product", direct_search_term: "melatonin", confidence: 0.95

Example 7 - Direct product request:
User: "show me vitamin C"
→ domain_slug: "wellness", extracted_problem: null, intent_type: "direct_product", direct_search_term: "vitamin C", confidence: 0.9

Example 8 - NOT direct_product (symptom, not product name):
User: "I'm so tired"
→ domain_slug: "wellness", extracted_problem: "low_energy", intent_type: "query", confidence: 0.9

Current User Message: "{state['user_message']}"
{f'''
Session context: The user is in an active consultation.
  Current domain: {state.get("domain_slug") or "unknown"}
  Pending prompt: "{state.get('extracted_context', {}).get('pending_slot_question')}"

FIRST check if the message is a budget or format filter on already-shown products:
  - Budget: "Under ₹1000", "cheaper", "under $50", "budget options", "under [number]"
  - Format: "Capsule form", "in powder", "liquid version", "capsules only"
  - Dietary filter (ONLY when phrased as a filter request): "Vegan options", "vegetarian only", "without fish", "no dairy", "show me vegan"
  If YES → classify as intent_type="filter", domain_slug="{state.get("domain_slug") or "wellness"}"

  IMPORTANT: bare dietary words like "Non Veg", "Vegan", "Vegetarian", "Pescatarian" WITHOUT "options"/"only"/"show me" are NOT filters — they are slot answers to the pending question.

If the message is a slot answer to the pending prompt (e.g. "yes", "no", "oily skin", "28", "Non Veg", "Vegan", "Intermediate") → classify as:
  intent_type="query", domain_slug="{state.get("domain_slug") or "wellness"}"
The interviewer will handle it from there.

If they are asking an educational question about an ingredient or supplement, classify as intent_type="ingredient_info".
''' if state.get("status") == "awaiting_slot" and state.get("extracted_context", {}).get("pending_slot_question") else f'''
Session context: The user has an active session in domain "{state.get("domain_slug")}".

FIRST check if the message is a budget or format filter on products:
  - Budget: "Under ₹1000", "cheaper", "under $50", "budget options", "under [number]", "under 1500", "below 500"
  - Format: "Capsule form", "in powder", "liquid version", "capsules only"
  - Dietary filter: "Vegan options", "vegetarian only", "without fish", "no dairy"
  If YES → classify as intent_type="filter", domain_slug="{state.get("domain_slug") or "wellness"}"
''' if state.get("domain_slug") and state.get("domain_slug") != "out_of_scope" else ""}"""

    model = get_router_model()
    result: RouterResponse = await model.ainvoke(system_prompt)

    # --- Awaiting-Slot Safety Override ---
    # When the user is answering a slot question (e.g. "Vegetarian", "Yes", "No",
    # "Oily skin"), single-word answers can be misclassified as out_of_scope or
    # a wrong domain by the LLM even with the context block.  If the session was
    # genuinely awaiting a slot answer (status + pending question + valid domain),
    # we NEVER let the router send the user to fallback — override to query in the
    # current session domain so the interviewer can process the answer.
    _original_status = state.get("status")
    _pending_q = (state.get("extracted_context") or {}).get("pending_slot_question")
    _session_domain = state.get("domain_slug")
    _known_domain_slugs = {d["domain"] for d in domains}

    if (
        _original_status == "awaiting_slot"
        and _pending_q
        and _session_domain
        and _session_domain not in ("out_of_scope", None)
        and result.intent_type not in ("filter", "ingredient_info")  # never override valid filter/info
        and (
            result.domain_slug == "out_of_scope"
            or result.domain_slug not in _known_domain_slugs
        )
    ):
        logger.warning(
            f"Awaiting-slot safety override: LLM classified "
            f"'{state.get('user_message')!r}' as domain='{result.domain_slug}' "
            f"but session is awaiting_slot in '{_session_domain}'. "
            f"Overriding to session domain with intent_type='query'."
        )
        result.domain_slug = _session_domain
        result.intent_type = "query"
        result.extracted_problem = None  # slot answer, not a new problem

    # Update state based on result
    new_state = state.copy()

    # --- Knowledge Graph Validation ---
    # If router extracted a problem, validate it against the knowledge graph
    problem_id = None
    graph_domain = None

    if result.extracted_problem and result.domain_slug != "out_of_scope":
        # Try to find the problem in available knowledge graphs
        available_graphs = list_available_graphs()
        logger.info(f"Router extracted problem '{result.extracted_problem}', validating against graphs")

        # Validate against the router's chosen domain FIRST to avoid
        # cross-domain false matches (e.g., "dull skin" matching "dull_hair"
        # in hair graph instead of "dull_skin" in skin graph)
        ordered_graphs = sorted(
            available_graphs,
            key=lambda g: (0 if g == result.domain_slug else 1)
        )

        for graph_name in ordered_graphs:
            try:
                problem = GraphQueryEngine.extract_problem_from_text(
                    domain=graph_name,
                    text=result.extracted_problem
                )

                if problem:
                    problem_id = problem['id']
                    graph_domain = graph_name
                    logger.info(
                        f"Validated problem '{problem_id}' (display: {problem.get('display_name')}) "
                        f"in graph '{graph_name}'"
                    )
                    break
            except Exception as e:
                logger.warning(f"Error validating against graph '{graph_name}': {e}")

        if problem_id and graph_domain:
            # Problem validated successfully
            if result.domain_slug != graph_domain:
                logger.info(
                    f"Graph suggests domain '{graph_domain}' instead of '{result.domain_slug}'. "
                    f"Using graph recommendation."
                )
                result.domain_slug = graph_domain
        else:
            # Problem extraction failed validation - interviewer will handle it
            logger.info(
                f"Could not validate extracted_problem='{result.extracted_problem}'. "
                f"Clearing it so interviewer can ask."
            )
            result.extracted_problem = None

    # --- Standard Routing Logic ---
    if result.domain_slug == "out_of_scope":
        new_state["domain_slug"] = "out_of_scope"
        new_state["intent_type"] = "query"
        new_state["status"] = "fallback_conversation"
        new_state["next_agent"] = "fallback"
    else:
        # Resolve slug to domain metadata
        domain_meta = next((d for d in domains if d['domain'] == result.domain_slug), None)
        if domain_meta:
            new_state["domain_slug"] = domain_meta['domain']
            new_state["intent_type"] = result.intent_type
            # ingredient_info preserves the caller's status so the interrupted
            # interview (awaiting_slot) can resume correctly after the answer.
            if result.intent_type != "ingredient_info":
                new_state["status"] = "collecting_info"

            # Never auto-assign the problem from the router.
            # The interviewer should always ask the user to confirm/specify
            # their concern, even if the router detected a candidate.
            if problem_id and graph_domain:
                logger.info(
                    f"Router detected candidate problem '{problem_id}' for domain "
                    f"'{graph_domain}', but deferring to interviewer to confirm with user."
                )
                # Store candidate problem so initial_products can use it
                # for semantic search while the interviewer confirms with user.
                existing_ctx = new_state.get("extracted_context", {})
                existing_ctx["candidate_problem"] = {
                    "problem_id": problem_id,
                    "graph_domain": graph_domain,
                    "confidence": result.confidence,
                }
                new_state["extracted_context"] = existing_ctx
            else:
                logger.info(
                    f"Router identified domain '{domain_meta['domain']}' but no specific problem. "
                    f"Interviewer will handle problem identification."
                )

            # Route based on intent type
            if result.intent_type == "filter":
                # Filter on already-shown products — preserve status so Refinement
                # and Safety know to restore the interview after filtering.
                new_state["intent_type"] = "filter"
                new_state["next_agent"] = "refinement"
                new_state["status"] = _original_status or new_state.get("status")
                # Seed inline constraints so Refinement's LLM call has a head-start
                if result.inline_constraints:
                    existing_ctx = new_state.get("extracted_context", {})
                    existing_ctx.update(result.inline_constraints)
                    new_state["extracted_context"] = existing_ctx
                logger.info(
                    f"Filter request detected during status='{_original_status}'. "
                    f"Routing to refinement (status preserved)."
                )
            elif result.intent_type == "ingredient_info":
                new_state["intent_type"] = "ingredient_info"
                new_state["next_agent"] = "ingredient_info"
                logger.info(
                    f"Ingredient info request detected. "
                    f"Routing to ingredient_info agent (status preserved)."
                )
            elif result.intent_type == "direct_product" and result.direct_search_term:
                # Direct product request — bypass interviewer, go straight to search.
                # Also merge any inline constraints (budget, dietary, format) so
                # Search can apply SQL-level price/attribute filters immediately.
                existing_ctx = new_state.get("extracted_context", {})
                existing_ctx["direct_search_term"] = result.direct_search_term
                if result.inline_constraints:
                    existing_ctx.update(result.inline_constraints)
                    logger.info(
                        f"Inline constraints extracted with direct product: {result.inline_constraints}"
                    )
                new_state["extracted_context"] = existing_ctx
                new_state["intent_type"] = "direct_product"
                new_state["next_agent"] = "search"
                logger.info(
                    f"Direct product request detected: '{result.direct_search_term}'. "
                    f"Bypassing interviewer, routing to search."
                )
            elif result.intent_type == "journey":
                new_state["next_agent"] = "journey"
            else:
                new_state["next_agent"] = "interviewer"
        else:
            # Fallback if AI hallucinates a slug
            logger.warning(f"Router classified to unknown domain '{result.domain_slug}'")
            new_state["status"] = "fallback_conversation"
            new_state["intent_type"] = "query"
            new_state["next_agent"] = "fallback"

    logger.info(
        f"Router decision: domain={new_state.get('domain_slug')}, "
        f"intent={new_state.get('intent_type')}, "
        f"next={new_state.get('next_agent')}, "
        f"problem_identified={bool(problem_id)}"
    )
    return new_state
