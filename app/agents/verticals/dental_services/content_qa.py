"""Content QA — answers procedural / educational questions by retrieving
the most relevant chunks of Dezy's website content (procedure pages, FAQs,
comparison pages) and synthesizing a calm plain-language answer with
citations.

If no useful chunks are retrieved (e.g. content not yet ingested for this
tenant), surface a graceful fallback that offers a consultation rather
than fabricating an answer.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.shared.llm import get_bedrock_llm
from app.agents.verticals.dental_services.knowledge import (
    COST_CALCULATOR_CTA,
    PERSONA_SYSTEM_PROMPT,
)
from app.agents.verticals.dental_services.state import DentalAgentState
from app.db.repositories.dental.content_chunk import ContentChunkRepository
from app.services.embeddings import generate_embedding_async

logger = logging.getLogger(__name__)


MIN_SIMILARITY = 0.55
TOP_K = 5


class ContentQAResponse(BaseModel):
    answer: str = Field(
        description=(
            "Plain-language answer grounded in the provided sources. Calm, "
            "non-pushy tone. 2-5 sentences. If sources don't fully answer the "
            "question, say so honestly and suggest booking a consultation."
        )
    )
    cited_chunk_ids: list[str] = Field(
        default_factory=list,
        description="IDs of the chunks you actually used to answer (subset of provided).",
    )
    suggested_replies: list[str] = Field(
        default_factory=list,
        description="2-3 short follow-up suggestions, each under 50 chars.",
    )


def _format_sources(chunks_with_score: list[tuple]) -> str:
    lines = []
    for chunk, score in chunks_with_score:
        # SQLAlchemy model attrs
        cid = str(chunk.id)
        title = chunk.title or chunk.source_url
        lines.append(
            f"[{cid}] (score={score:.2f}) {title}\n{chunk.chunk_text.strip()[:1000]}\n"
        )
    return "\n---\n".join(lines)


def _build_prompt(user_message: str, sources_text: str) -> str:
    return f"""{PERSONA_SYSTEM_PROMPT}

The patient asked: "{user_message}"

Below are excerpts from Dezy's published content (procedure pages, FAQs,
comparisons). Each excerpt is prefixed with [id] and a similarity score.
Use ONLY information from these excerpts in your answer. If they don't
cover the question, say so plainly and suggest booking a consultation.

SOURCES:
{sources_text}

Rules:
- 2-5 sentences. Plain language. No jargon.
- Cite the chunk ids you actually used in `cited_chunk_ids`.
- Never invent facts. Never claim guaranteed outcomes.
- Acknowledge any anxiety in the patient's wording if present.
"""


async def content_qa_agent(state: DentalAgentState, db: AsyncSession) -> DentalAgentState:
    user_message = state.get("user_message", "").strip()
    tenant_id = state.get("tenant_id")

    if not user_message or tenant_id is None:
        state["response"] = (
            "Could you share a bit more detail about what you'd like to know? "
            "I can answer questions about procedures, recovery, pain, or sittings."
        )
        state["items"] = []
        return state

    # 1) Embed the question
    try:
        query_embedding = await generate_embedding_async(user_message)
    except Exception as e:
        logger.warning("content_qa embedding failed: %s", e)
        state["response"] = (
            "I'm having trouble looking up the answer right now. The fastest way "
            "to get a clear, personalised answer is a free consultation."
        )
        return state

    # 2) Retrieve top chunks
    repo = ContentChunkRepository(db)
    chunks = await repo.search_by_embedding(
        tenant_id=tenant_id,
        query_embedding=query_embedding,
        top_k=TOP_K,
        min_similarity=MIN_SIMILARITY,
    )

    if not chunks:
        # Graceful fallback when content isn't ingested (or no good match)
        state["response"] = (
            "I don't have a confident answer to that from Dezy's published material "
            "yet. The most accurate next step is a free consultation — a Dezy clinician "
            "can walk you through this specifically for your situation."
        )
        state["cta_links"] = [COST_CALCULATOR_CTA]
        state["items"] = []
        state["suggested_replies"] = ["Talk to a dentist", "Show me prices", "Find a doctor"]
        return state

    # 3) Synthesize an answer grounded in retrieved chunks
    sources_text = _format_sources(chunks)
    model = get_bedrock_llm(structured_output_schema=ContentQAResponse)
    try:
        result: ContentQAResponse = await model.ainvoke(
            _build_prompt(user_message, sources_text)
        )
    except Exception as e:
        logger.warning("content_qa LLM failed: %s", e)
        # Fall back to the best single chunk as a quote
        best_chunk, _ = chunks[0]
        state["response"] = (
            f"Here's what Dezy's material says about that:\n\n"
            f"> {best_chunk.chunk_text.strip()[:600]}\n\n"
            "A clinician can answer this more specifically during a free consultation."
        )
        state["cta_links"] = [COST_CALCULATOR_CTA]
        return state

    cited_ids = set(result.cited_chunk_ids)
    citations = [
        {
            "chunk_id": str(c.id),
            "url": c.source_url,
            "title": c.title or c.source_url,
            "snippet": c.chunk_text.strip()[:240],
        }
        for c, _ in chunks
        if str(c.id) in cited_ids
    ] or [
        # Fall back to top-1 if the LLM didn't echo any ids
        {
            "chunk_id": str(chunks[0][0].id),
            "url": chunks[0][0].source_url,
            "title": chunks[0][0].title or chunks[0][0].source_url,
            "snippet": chunks[0][0].chunk_text.strip()[:240],
        }
    ]

    state["response"] = result.answer
    state["items"] = []
    state["cta_links"] = [COST_CALCULATOR_CTA]
    state["suggested_replies"] = result.suggested_replies or []
    state["content_citations"] = citations
    state["status"] = "completed"
    return state
