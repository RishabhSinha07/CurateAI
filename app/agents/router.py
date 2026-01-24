from typing import List, Optional
from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.repositories.domain import DomainRepository
from app.agents.state import AgentState

settings = get_settings()

class RouterResponse(BaseModel):
    """Structured response from the Router agent."""
    domain_slug: str = Field(description="The slug of the identified domain or 'out_of_scope'")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")
    reasoning: str = Field(description="Brief explanation for the classification")

def get_router_model():
    """Initialize the Bedrock model for routing."""
    llm = ChatBedrock(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        model_kwargs={"temperature": 0},
    )
    return llm.with_structured_output(RouterResponse)

async def router_agent(state: AgentState, db: AsyncSession) -> AgentState:
    """
    Classifies the user's message into a specific domain.
    """
    domain_repo = DomainRepository(db)
    domains = await domain_repo.get_all_active()
    
    # Format domain descriptions for the prompt
    domain_descriptions = "\n".join([
        f"- {d.slug}: {d.name}. Use this for: {d.system_persona or 'General requests in this category'}"
        for d in domains
    ])
    
    system_prompt = f"""You are a specialized Triage Agent for CurateAI. Your goal is to map the user's request to the most appropriate product specialist (domain).

Available Domains:
{domain_descriptions}
- out_of_scope: Use this for requests that are not related to wellness, supplements, health goals, or any of the domains listed above (e.g., small talk, weather, politics).

Guidelines:
1. If the user's intent is clear, pick the specific domain.
2. If the user's intent is related to wellness but ambiguous, pick the most likely domain.
3. If the user's intent is completely unrelated to the available categories, select 'out_of_scope'.

Current User Message: "{state['user_message']}"
"""

    model = get_router_model()
    result: RouterResponse = await model.ainvoke(system_prompt)
    
    # Update state based on result
    new_state = state.copy()
    
    if result.domain_slug == "out_of_scope":
        new_state["domain_slug"] = "out_of_scope"
        new_state["domain_id"] = None
        new_state["status"] = "out_of_scope"
        new_state["next_agent"] = "safety" # Redirect to safety for a friendly rejection
    else:
        # Resolve slug to ID
        domain = next((d for d in domains if d.slug == result.domain_slug), None)
        if domain:
            new_state["domain_id"] = domain.id
            new_state["domain_slug"] = domain.slug
            new_state["domain_config"] = domain.get_merged_config()
            new_state["status"] = "collecting_info"
            new_state["next_agent"] = "interviewer"
        else:
            # Fallback if AI hallucinates a slug
            new_state["status"] = "out_of_scope"
            new_state["next_agent"] = "safety"

    return new_state
