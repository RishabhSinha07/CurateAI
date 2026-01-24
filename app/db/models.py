import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

if TYPE_CHECKING:
    pass


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Domain(Base):
    """
    AI Specialist configuration table.

    Defines how the AI behaves for different product categories,
    including required slots to fill and search filters to apply.
    """

    __tablename__ = "domains"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    parent_domain_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("domains.id"), nullable=True
    )
    config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Schema: {required_slots: [], optional_slots: [], search_filters: [], safety_disclaimers: []}",
    )
    system_persona: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    parent: Mapped["Domain | None"] = relationship(
        "Domain", remote_side=[id], back_populates="children"
    )
    children: Mapped[list["Domain"]] = relationship("Domain", back_populates="parent")
    products: Mapped[list["Product"]] = relationship("Product", back_populates="domain")
    sessions: Mapped[list["ChatSession"]] = relationship("ChatSession", back_populates="domain")

    def get_merged_config(self) -> dict:
        """
        Returns config with parent's arrays merged in.
        Child arrays extend parent arrays; child persona overrides parent.
        """
        if self.parent is None:
            return self.config

        parent_config = self.parent.get_merged_config()
        merged = {}

        # Merge array fields (child extends parent)
        for key in ["required_slots", "optional_slots", "search_filters", "safety_disclaimers"]:
            parent_values = parent_config.get(key, [])
            child_values = self.config.get(key, [])
            merged[key] = list(dict.fromkeys(parent_values + child_values))  # Dedupe, preserve order

        return merged


class Product(Base):
    """
    Universal product catalog with flexible JSONB attributes.

    Supports any domain (wellness, tools, etc.) through the
    polymorphic attributes column.
    """

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    domain_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("domains.id"), nullable=False, index=True
    )
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    inventory_count: Mapped[int] = mapped_column(default=0, nullable=False)
    product_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Domain-specific attributes (ingredients, voltage, etc.)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Vector embedding for semantic search (AWS Titan v2 = 1024 dims)
    description_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    domain: Mapped["Domain"] = relationship("Domain", back_populates="products")

    __table_args__ = (
        Index("idx_products_attributes", "attributes", postgresql_using="gin"),
        Index(
            "idx_products_embedding",
            "description_embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"description_embedding": "vector_cosine_ops"},
        ),
    )


class ChatSession(Base):
    """
    Active consultation state.

    Tracks the current domain, filled slots (extracted_context),
    and session status for multi-turn conversations.
    """

    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # Optional for guests
    current_domain_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("domains.id"), nullable=True
    )

    # Slot state: {"skin_type": "oily", "budget": 50, "goal": "dark spots"}
    extracted_context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # active, collecting_info, awaiting_slot, completed
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    domain: Mapped["Domain | None"] = relationship("Domain", back_populates="sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="session", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base):
    """
    Chronological conversation history.

    Stores messages with role (user/assistant/system) and
    optional product recommendations for audit and context.
    """

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(15), nullable=False
    )  # 'user', 'assistant', 'system'
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Products recommended in this message
    suggested_product_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(Uuid), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")
