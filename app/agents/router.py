from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.config import get_settings
from app.agents.state import AgentState
from app.knowledge.query_engine import GraphQueryEngine
from app.knowledge.graph_loader import list_available_graphs, get_all_active_domains, get_knowledge_graph

settings = get_settings()
logger = logging.getLogger(__name__)

class RouterResponse(BaseModel):
    """Structured response from the Router agent."""
    domain_slug: str = Field(description="The slug of the identified domain or 'out_of_scope'")
    intent_type: str = Field(
        description="Type of intent: 'query' for specific product search or 'journey' for customer journey bundle"
    )
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")
    reasoning: str = Field(default="", description="Brief explanation for the classification")
    extracted_problem: Optional[str] = Field(
        default=None,
        description="Extracted problem or health goal from user message if clearly stated (e.g., 'low energy', 'poor sleep'). Leave null if unclear - the interviewer will ask."
    )

def get_router_model():
    """Initialize the Bedrock model for routing."""
    llm = ChatBedrock(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        model_kwargs={"temperature": 0},
    )
    return llm.with_structured_output(RouterResponse)


def _build_dynamic_problem_reference() -> str:
    """
    Build a dynamic problem reference by loading all active knowledge graphs
    and extracting their problems with synonyms.

    Returns:
        Formatted string with problem categories and examples for the router prompt
    """
    domains = get_all_active_domains()
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
    # Load domains from knowledge graphs
    domains = get_all_active_domains()

    # Format domain descriptions for the prompt
    domain_descriptions = "\n".join([
        f"- {d['domain']}: {d['display_name']}. Use this for: {d.get('persona', 'General requests')}"
        for d in domains
    ])

    # Dynamically build problem reference from all knowledge graphs
    problem_reference = _build_dynamic_problem_reference()

    system_prompt = f"""You are a specialized Triage Agent for CurateAI. Your job is to identify the domain and optionally extract the problem if clearly stated.

Available Domains:
{domain_descriptions}
- out_of_scope: Use this for requests that are not related to wellness, supplements, health goals, or any of the domains listed above (e.g., small talk, weather, politics).

Intent Types:
1. **journey**: The user is starting a new activity, phase, or routine and needs a comprehensive set of products for that journey.
   - Keywords: "starting", "new to", "beginner", "getting into", "beginning", "first time", "just started"
   - Examples: "I'm starting gym", "new to skincare", "beginning my fitness journey", "getting into running"

2. **query**: The user has a specific need, problem, or is looking for particular product types.
   - Examples: "I need protein powder", "looking for moisturizer for dry skin", "best pre-workout for energy"

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

Current User Message: "{state['user_message']}"
"""

    model = get_router_model()
    result: RouterResponse = await model.ainvoke(system_prompt)

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

        for graph_name in available_graphs:
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
        new_state["status"] = "out_of_scope"
        new_state["next_agent"] = "safety"
    else:
        # Resolve slug to domain metadata
        domain_meta = next((d for d in domains if d['domain'] == result.domain_slug), None)
        if domain_meta:
            new_state["domain_slug"] = domain_meta['domain']
            new_state["intent_type"] = result.intent_type
            new_state["status"] = "collecting_info"

            # Never auto-assign the problem from the router.
            # The interviewer should always ask the user to confirm/specify
            # their concern, even if the router detected a candidate.
            if problem_id and graph_domain:
                logger.info(
                    f"Router detected candidate problem '{problem_id}' for domain "
                    f"'{graph_domain}', but deferring to interviewer to confirm with user."
                )
            else:
                logger.info(
                    f"Router identified domain '{domain_meta['domain']}' but no specific problem. "
                    f"Interviewer will handle problem identification."
                )

            # Route based on intent type
            if result.intent_type == "journey":
                new_state["next_agent"] = "journey"
            else:
                new_state["next_agent"] = "interviewer"
        else:
            # Fallback if AI hallucinates a slug
            logger.warning(f"Router classified to unknown domain '{result.domain_slug}'")
            new_state["status"] = "out_of_scope"
            new_state["intent_type"] = "query"
            new_state["next_agent"] = "safety"

    logger.info(
        f"Router decision: domain={new_state.get('domain_slug')}, "
        f"intent={new_state.get('intent_type')}, "
        f"next={new_state.get('next_agent')}, "
        f"problem_identified={bool(problem_id)}"
    )
    return new_state
