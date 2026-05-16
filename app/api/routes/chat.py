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
from app.agents.graph import create_initial_state
from app.agents.shared.registry import get_vertical
from app.api.middleware.auth import TenantContext, get_tenant_context
from app.api.middleware.rate_limit import check_rate_limit

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
    description: Optional[str] = None
    match_reasons: list[str]


class ProductDetail(BaseModel):
    """Full product detail returned when PDA responds."""
    id: str
    name: str
    brand: Optional[str] = None
    price: Optional[float] = None
    currency: str = "USD"
    product_url: Optional[str] = None
    image_url: Optional[str] = None
    description: Optional[str] = None
    attributes: dict = {}


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
    product_detail: Optional[ProductDetail] = None  # Full product info when PDA responds


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    tenant: TenantContext = Depends(check_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """
    Process a chat message and return AI consultation response.

    This endpoint handles the full multi-agent flow:
    1. Creates or retrieves session
    2. Runs the consultation graph
    3. Persists messages and context
    4. Returns response with any product recommendations
    """
    session_repo = SessionRepository(db)

    # Get or create session (with tenant ownership check)
    try:
        chat_session = await session_repo.get_or_create(
            session_id=request.session_id,
            tenant_id=tenant.tenant_id,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Session not found")

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
        tenant_id=tenant.tenant_id,
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
        tenant_id=tenant.tenant_id,
        tenant_enabled_domains=tenant.enabled_domains,
    )

    # Dispatch to the vertical that owns this tenant's agent graph.
    vertical = get_vertical(tenant.vertical)
    try:
        final_state = await vertical.run(initial_state, db)
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

    # Persist shown products in extracted_context so they survive across turns.
    # This lets Router/Refinement detect product_detail intent and PDA match
    # against the products the user has actually seen.
    if display_products:
        ctx = final_state.get("extracted_context") or {}
        ctx["shown_products"] = [
            {k: p.get(k) for k in ("id", "name", "brand", "description", "price", "currency",
                                    "product_url", "image_url", "attributes", "match_reasons")}
            for p in display_products[:8]
        ]
        final_state["extracted_context"] = ctx
        await session_repo.update_context(chat_session.id, ctx)

    # Save assistant response
    product_ids = None
    if display_products:
        product_ids = [uuid.UUID(p["id"]) for p in display_products]

    await session_repo.add_message(
        session_id=chat_session.id,
        tenant_id=tenant.tenant_id,
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
            description=p.get("description"),
            match_reasons=p.get("match_reasons", [])
        ))

    # Get journey info if present
    journey_info = final_state.get("journey_bundle")
    intent_type = final_state.get("intent_type")

    # Get product detail if PDA responded
    product_detail_data = None
    if final_state.get("product_context"):
        pc = final_state["product_context"]
        product_detail_data = ProductDetail(
            id=pc.get("id", ""),
            name=pc.get("name", ""),
            brand=pc.get("brand"),
            price=pc.get("price"),
            currency=pc.get("currency", "USD"),
            product_url=pc.get("product_url"),
            image_url=pc.get("image_url"),
            description=pc.get("description"),
            attributes=pc.get("attributes", {}),
        )

    return ChatResponse(
        session_id=chat_session.id,
        response=response_text,
        status=new_status,
        domain_slug=final_state.get("domain_slug"),
        intent_type=intent_type,
        products=recommendations,
        suggested_replies=final_state.get("suggested_replies", []),
        journey_info=journey_info,
        product_detail=product_detail_data,
    )


@router.get("/{session_id}/history")
async def get_chat_history(
    session_id: uuid.UUID,
    limit: int = 20,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
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
