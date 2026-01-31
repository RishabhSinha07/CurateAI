import uuid
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import ChatSession, ChatMessage

class SessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, session_id: Optional[uuid.UUID] = None) -> ChatSession:
        """Get an existing session or create a new one."""
        if session_id:
            db_session = await self.session.get(ChatSession, session_id)
            if db_session:
                return db_session
        
        # Create new session if ID not provided or not found
        new_session = ChatSession(id=session_id or uuid.uuid4())
        self.session.add(new_session)
        await self.session.flush() # Ensure ID is generated/available
        return new_session

    async def update_context(self, session_id: uuid.UUID, context_updates: dict) -> ChatSession:
        """Update the extracted_context JSONB field."""
        curr_session = await self.get_or_create(session_id)
        
        # Merge existing context with updates
        updated_context = {**curr_session.extracted_context, **context_updates}
        
        await self.session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(extracted_context=updated_context)
        )
        await self.session.refresh(curr_session)
        return curr_session

    async def set_domain(self, session_id: uuid.UUID, domain_slug: str) -> None:
        """Set the current domain for the session."""
        await self.session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(current_domain_slug=domain_slug)
        )

    async def add_message(
        self, 
        session_id: uuid.UUID, 
        role: str, 
        content: str, 
        suggested_product_ids: Optional[list[uuid.UUID]] = None
    ) -> ChatMessage:
        """Add a new message to the session history."""
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            suggested_product_ids=suggested_product_ids
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def get_history(self, session_id: uuid.UUID, limit: int = 10) -> list[ChatMessage]:
        """Get recent message history for a session."""
        result = await self.session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        # Reverse to get chronological order
        messages = list(result.scalars().all())
        messages.reverse()
        return messages

    async def update_status(self, session_id: uuid.UUID, status: str) -> None:
        """Update session status (e.g., active, completed)."""
        await self.session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(status=status)
        )
