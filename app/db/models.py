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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

if TYPE_CHECKING:
    pass


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


# Domain model removed - domain configuration now managed via knowledge graphs


class Product(Base):
    """
    Universal product catalog with flexible JSONB attributes.

    Supports any domain (wellness, tools, etc.) through the
    polymorphic attributes column.

    Products can belong to multiple domains via domain_slugs array.
    """

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    domain_slugs: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), nullable=False
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

    # Relationships removed - domain now referenced by slug only

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
    current_domain_slug: Mapped[str | None] = mapped_column(
        String(50), nullable=True
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


class JourneyBundle(Base):
    """
    Journey bundle templates for customer journeys.

    Stores predefined product bundles for common customer journeys
    (e.g., starting gym, skincare routine, new runner) with usage guidance.
    """

    __tablename__ = "journey_bundles"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    domain_slug: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    journey_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Keywords for journey detection (e.g., ["starting gym", "beginner fitness"])
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)

    # Product categories needed for this journey (e.g., ["protein", "pre_workout"])
    product_categories: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)

    # Optional product tags for filtering (e.g., ["beginner_friendly", "essential"])
    product_tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # Usage guidance templates per category
    # Example: {"protein": "Take after workouts...", "pre_workout": "Consume 15-20 mins before..."}
    guidance_templates: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships removed - domain now referenced by slug only

    __table_args__ = (
        Index("idx_journey_bundles_keywords", "keywords", postgresql_using="gin"),
        # Unique constraint on domain_slug + journey_id
        UniqueConstraint("domain_slug", "journey_id", name="uq_journey_bundle_domain_journey"),
    )

