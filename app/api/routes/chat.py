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
from app.db.repositories.widget_user import WidgetUserRepository
from app.db.session import get_db

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""

    message: str = Field(..., min_length=1, max_length=2000, description="User message")
    session_id: Optional[uuid.UUID] = Field(
        None, description="Existing session ID for continuation"
    )
    # Stable per-visitor id minted by the widget and persisted in localStorage.
    # Omitted by non-widget callers (admin UI, tests); when present, the route
    # enforces the lead-capture gate against tenants.free_message_limit.
    anonymous_id: Optional[str] = Field(
        None, max_length=64, description="Widget visitor ID from localStorage"
    )


class RegisterRequest(BaseModel):
    """Lead-capture payload — flips an anonymous visitor to registered."""

    anonymous_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=1, max_length=255)
    phone: str = Field(..., min_length=1, max_length=50)


class RegisterResponse(BaseModel):
    status: str


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    tenant: TenantContext = Depends(check_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Process a chat message and return a polymorphic consultation response."""
    session_repo = SessionRepository(db)
    widget_user_repo = WidgetUserRepository(db)

    # Lead-capture gate: when the widget supplies an anonymous_id, count the
    # incoming user message against the tenant's free quota. Once an
    # unregistered visitor exceeds the quota, short-circuit with
    # status="auth_required" so the widget can render the registration form.
    widget_user = None
    if request.anonymous_id:
        widget_user = await widget_user_repo.get_or_create(
            tenant_id=tenant.tenant_id,
            anonymous_id=request.anonymous_id,
        )
        if (
            not widget_user.is_registered
            and widget_user.message_count >= tenant.free_message_limit
        ):
            existing_session_id = (
                request.session_id if request.session_id else uuid.uuid4()
            )
            return ChatResponse(
                session_id=existing_session_id,
                response=(
                    "Before we continue, could you share your name, email, "
                    "and phone number? It just takes a moment and helps us "
                    "stay in touch."
                ),
                status="auth_required",
            )

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

    if widget_user is not None and not widget_user.is_registered:
        await widget_user_repo.increment_message_count(widget_user.id)

    return response


@router.post("/register", response_model=RegisterResponse)
async def register_widget_user(
    request: RegisterRequest,
    tenant: TenantContext = Depends(check_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Lift the lead-capture gate for an anonymous visitor.

    Stores name/email/phone as-is — no validation here per design; verification
    (if any) is the caller's responsibility.
    """
    widget_user_repo = WidgetUserRepository(db)
    await widget_user_repo.mark_registered(
        tenant_id=tenant.tenant_id,
        anonymous_id=request.anonymous_id,
        name=request.name,
        email=request.email,
        phone=request.phone,
    )
    return RegisterResponse(status="ok")


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
