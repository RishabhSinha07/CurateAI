"""Chat API endpoint.

The route is vertical-agnostic. It resolves the tenant's vertical via the
registry and delegates state construction, graph execution, persistence,
and response building to the vertical. The kernel only handles
session-level concerns (get/create session, save user/assistant messages,
update status/context).
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.shared.registry import get_vertical
from app.agents.shared.response import ChatResponse
from app.api.middleware.auth import TenantContext, get_tenant_context
from app.api.middleware.rate_limit import check_rate_limit
from app.db.repositories.session import SessionRepository
from app.db.session import get_db

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""

    message: str = Field(..., min_length=1, max_length=2000, description="User message")
    session_id: Optional[uuid.UUID] = Field(
        None, description="Existing session ID for continuation"
    )


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    tenant: TenantContext = Depends(check_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Process a chat message and return a polymorphic consultation response."""
    session_repo = SessionRepository(db)

    try:
        chat_session = await session_repo.get_or_create(
            session_id=request.session_id,
            tenant_id=tenant.tenant_id,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Session not found")

    # Pull last assistant message for slot-extraction context.
    previous_response: str | None = None
    if chat_session.status in ("awaiting_slot", "fallback_conversation"):
        history = await session_repo.get_history(chat_session.id, limit=5)
        for msg in reversed(history):
            if msg.role == "assistant":
                previous_response = msg.content
                break

    # Save the user message before invoking the graph.
    await session_repo.add_message(
        session_id=chat_session.id,
        tenant_id=tenant.tenant_id,
        role="user",
        content=request.message,
    )

    # Dispatch to the vertical that owns this tenant's agent graph.
    vertical = get_vertical(tenant.vertical)

    state = vertical.create_state(
        session_id=chat_session.id,
        user_message=request.message,
        existing_context=chat_session.extracted_context,
        existing_status=chat_session.status,
        previous_response=previous_response,
        tenant_id=tenant.tenant_id,
        tenant_enabled_domains=tenant.enabled_domains,
        vertical_context_seed={"domain_slug": chat_session.current_domain_slug},
    )

    try:
        state = await vertical.run(state, db)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred during consultation: {str(e)}",
        )

    # Vertical-specific persistence + response build.
    response, item_ids = await vertical.finalize(
        state=state,
        session_repo=session_repo,
        session_id=chat_session.id,
        tenant_id=tenant.tenant_id,
    )

    # Generic kernel persistence: status and any context updates the graph made.
    new_context = state.get("extracted_context")
    if new_context:
        await session_repo.update_context(chat_session.id, new_context)

    new_status = state.get("status", "active")
    if new_status != chat_session.status:
        await session_repo.update_status(chat_session.id, new_status)

    # Save the assistant message, attaching opaque item IDs for analytics
    # and downstream agents (refinement, product-detail matching).
    await session_repo.add_message(
        session_id=chat_session.id,
        tenant_id=tenant.tenant_id,
        role="assistant",
        content=response.response,
        suggested_product_ids=item_ids or None,
    )

    return response


@router.get("/{session_id}/history")
async def get_chat_history(
    session_id: uuid.UUID,
    limit: int = 20,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return chat history for a session."""
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
                "suggested_item_ids": [str(pid) for pid in (m.suggested_product_ids or [])],
            }
            for m in messages
        ],
    }
