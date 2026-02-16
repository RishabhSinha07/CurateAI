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
    domain_slug: Optional[str] = None  # Identified domain
    intent_type: Optional[str] = None  # "query" or "journey"
    products: list[ProductRecommendation] = []
    suggested_replies: list[str] = []
    journey_info: Optional[dict] = None  # Journey bundle info if intent_type is "journey"


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

    # Get or create session
    chat_session = await session_repo.get_or_create(request.session_id)

    # Load existing domain slug if session has one
    domain_slug = chat_session.current_domain_slug

    # Get the last assistant message for context (helps with slot extraction)
    previous_response = None
    if chat_session.status in ("awaiting_slot", "fallback_conversation"):
        # Get last few messages to find the most recent assistant message
        history = await session_repo.get_history(chat_session.id, limit=5)
        # Find the last assistant message (history is in chronological order)
        for msg in reversed(history):
            if msg.role == "assistant":
                previous_response = msg.content
                break

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
        domain_slug=domain_slug,
        previous_response=previous_response,
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

    if final_state.get("domain_slug") and final_state["domain_slug"] != domain_slug:
        await session_repo.set_domain(chat_session.id, final_state["domain_slug"])

    # Update session status
    new_status = final_state.get("status", "active")
    if new_status != chat_session.status:
        await session_repo.update_status(chat_session.id, new_status)

    # Use final (personalised) products when available, otherwise fall back
    # to the initial domain products shown during the first interview pass.
    final_products = final_state.get("final_products", [])
    display_products = final_products or final_state.get("initial_products", [])

    # Save assistant response
    product_ids = None
    if display_products:
        product_ids = [uuid.UUID(p["id"]) for p in display_products]

    await session_repo.add_message(
        session_id=chat_session.id,
        role="assistant",
        content=response_text,
        suggested_product_ids=product_ids
    )

    # Build product recommendations
    recommendations = []
    for p in display_products:
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

    # Get journey info if present
    journey_info = final_state.get("journey_bundle")
    intent_type = final_state.get("intent_type")

    return ChatResponse(
        session_id=chat_session.id,
        response=response_text,
        status=new_status,
        domain_slug=final_state.get("domain_slug"),
        intent_type=intent_type,
        products=recommendations,
        suggested_replies=final_state.get("suggested_replies", []),
        journey_info=journey_info
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
