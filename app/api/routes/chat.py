"""
Chat API endpoint for product consultations.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.repositories.session import SessionRepository
from app.db.repositories.domain import DomainRepository
from app.agents.graph import get_consultation_graph, create_initial_state

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""
    message: str = Field(..., min_length=1, max_length=2000, description="User message")
    session_id: Optional[uuid.UUID] = Field(None, description="Existing session ID for continuation")


class ProductRecommendation(BaseModel):
    """A product recommendation in the response."""
    id: str
    name: str
    brand: Optional[str]
    price: Optional[float]
    currency: str
    product_url: Optional[str]
    image_url: Optional[str]
    match_reasons: list[str]


class ChatResponse(BaseModel):
    """Response body for chat endpoint."""
    session_id: uuid.UUID
    response: str
    status: str
    products: list[ProductRecommendation] = []


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)) -> ChatResponse:
    """
    Process a chat message and return AI consultation response.

    This endpoint handles the full multi-agent flow:
    1. Creates or retrieves session
    2. Runs the consultation graph
    3. Persists messages and context
    4. Returns response with any product recommendations
    """
    session_repo = SessionRepository(db)
    domain_repo = DomainRepository(db)

    # Get or create session
    chat_session = await session_repo.get_or_create(request.session_id)

    # Load existing domain config if session has one
    domain_id = chat_session.current_domain_id
    domain_slug = None
    domain_config = None

    if domain_id:
        domain = await domain_repo.get_by_id(domain_id)
        if domain:
            domain_slug = domain.slug
            domain_config = domain.get_merged_config()

    # Save user message
    await session_repo.add_message(
        session_id=chat_session.id,
        role="user",
        content=request.message
    )

    # Create initial state for graph execution
    initial_state = create_initial_state(
        session_id=chat_session.id,
        user_message=request.message,
        existing_context=chat_session.extracted_context,
        existing_status=chat_session.status,
        domain_id=domain_id,
        domain_slug=domain_slug,
        domain_config=domain_config,
    )

    # Run the consultation graph
    graph = get_consultation_graph()
    try:
        final_state = await graph.run(initial_state, db)
    except Exception as e:
        # Log and return graceful error
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred during consultation: {str(e)}"
        )

    # Extract response
    response_text = final_state.get("response") or "I'm sorry, I couldn't process your request. Please try again."

    # Update session with new context and domain
    if final_state.get("extracted_context"):
        await session_repo.update_context(chat_session.id, final_state["extracted_context"])

    if final_state.get("domain_id") and final_state["domain_id"] != domain_id:
        await session_repo.set_domain(chat_session.id, final_state["domain_id"])

    # Update session status
    new_status = final_state.get("status", "active")
    if new_status != chat_session.status:
        await session_repo.update_status(chat_session.id, new_status)

    # Save assistant response
    product_ids = None
    final_products = final_state.get("final_products", [])
    if final_products:
        product_ids = [uuid.UUID(p["id"]) for p in final_products]

    await session_repo.add_message(
        session_id=chat_session.id,
        role="assistant",
        content=response_text,
        suggested_product_ids=product_ids
    )

    # Build product recommendations
    recommendations = []
    for p in final_products:
        recommendations.append(ProductRecommendation(
            id=p["id"],
            name=p["name"],
            brand=p.get("brand"),
            price=p.get("price"),
            currency=p.get("currency", "USD"),
            product_url=p.get("product_url"),
            image_url=p.get("image_url"),
            match_reasons=p.get("match_reasons", [])
        ))

    return ChatResponse(
        session_id=chat_session.id,
        response=response_text,
        status=new_status,
        products=recommendations
    )


@router.get("/{session_id}/history")
async def get_chat_history(
    session_id: uuid.UUID,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Get chat history for a session.
    """
    session_repo = SessionRepository(db)
    messages = await session_repo.get_history(session_id, limit=limit)

    return {
        "session_id": session_id,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
                "suggested_product_ids": [str(pid) for pid in (m.suggested_product_ids or [])]
            }
            for m in messages
        ]
    }
