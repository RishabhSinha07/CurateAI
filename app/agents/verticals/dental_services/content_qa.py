"""Content QA — answers procedural/educational questions via RAG over
content_chunks. Stub in slice A; real RAG in slice C.
"""

from __future__ import annotations

from app.agents.verticals.dental_services.state import DentalAgentState


async def content_qa_agent(state: DentalAgentState) -> DentalAgentState:
    state["response"] = (
        "I can answer procedural questions about Dezy's treatments — recovery, pain, "
        "step-by-step process. The content retrieval pipeline is being wired in this phase."
    )
    state.setdefault("items", [])
    state.setdefault("cta_links", [])
    return state
