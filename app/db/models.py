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
    Integer,
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


# ============================================
# Tenant & API Key Models
# ============================================


class Tenant(Base):
    """
    Tenant represents a company using CurateAI.

    Each tenant has its own products, sessions, and API keys.
    """

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    vertical: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="commerce"
    )
    enabled_domains: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), nullable=False, server_default="{*}"
    )
    allowed_origins: Mapped[list[str]] = mapped_column(
        ARRAY(String(500)), nullable=False, server_default="{*}"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    daily_bedrock_cost_cap_cents: Mapped[int] = mapped_column(
        Integer, default=500, nullable=False
    )
    # Max user messages an anonymous widget visitor can send before being
    # asked to register name/email/phone. Per-tenant so each customer can tune
    # their lead-capture aggressiveness.
    free_message_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="3"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    api_keys: Mapped[list["ApiKey"]] = relationship("ApiKey", back_populates="tenant")


class ApiKey(Base):
    """
    API key for tenant authentication.

    Keys are stored as SHA-256 hashes. The raw key is only shown once at creation.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    allowed_ips: Mapped[list[str] | None] = mapped_column(ARRAY(String(45)), nullable=True)
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="api_keys")


class AdminUser(Base):
    """
    Admin user mapped to a tenant.

    Used by the dashboard to authenticate admins and resolve
    which tenant they belong to.
    """

    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="owner", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant")


class WidgetUser(Base):
    """
    Anonymous-or-registered widget visitor, identified by a localStorage UUID.

    Tracks how many user messages an anonymous visitor has sent so the
    backend can gate further consultation behind a lead-capture form
    (name / email / phone). Once `is_registered=True`, the gate no longer
    fires for that visitor.
    """

    __tablename__ = "widget_users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # UUID generated client-side by the widget and persisted in localStorage.
    # Bypassable (incognito / cleared storage); accepted as the cost of a
    # frictionless first-message experience.
    anonymous_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "anonymous_id", name="uq_widget_users_tenant_anon"
        ),
    )


# ============================================
# Core Models
# ============================================

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
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, index=True
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
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, index=True
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
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, index=True
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
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, index=True
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

    __table_args__ = (
        Index("idx_journey_bundles_keywords", "keywords", postgresql_using="gin"),
        # Unique constraint on domain_slug + journey_id
        UniqueConstraint("domain_slug", "journey_id", name="uq_journey_bundle_domain_journey"),
    )


# ============================================
# Analytics Models
# ============================================


class ProductEvent(Base):
    """
    Tracks product interaction events (click, add_to_cart, purchase).
    Used for analytics and conversion tracking.
    """

    __tablename__ = "product_events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # click, add_to_cart, purchase
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_product_events_type_created", "event_type", "created_at"),
    )


# ============================================
# Dental Services Vertical Models
# ============================================
#
# These tables back the `dental_services` vertical. They live alongside the
# commerce-vertical Product table; both are tenant-scoped and each tenant
# uses one or the other based on `tenants.vertical`.


class Service(Base):
    """
    A treatment or service offered to patients (e.g. "Single Tooth Implant",
    "Clear Aligners", "Teeth Whitening").
    """

    __tablename__ = "services"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # implants | orthodontics | cosmetic | general | ...
    subcategory: Mapped[str | None] = mapped_column(String(80), nullable=True)
    short_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recovery_period: Mapped[str | None] = mapped_column(String(80), nullable=True)
    price_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_max: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    emi_eligible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
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

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_services_tenant_slug"),
        Index("idx_services_attributes", "attributes", postgresql_using="gin"),
        Index(
            "idx_services_embedding",
            "description_embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"description_embedding": "vector_cosine_ops"},
        ),
    )


class Clinic(Base):
    """A physical clinic location where services are delivered."""

    __tablename__ = "clinics"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), default="IN", nullable=False)
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hours: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    services_offered: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(Uuid), nullable=True
    )
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_clinics_tenant_slug"),
    )


class Doctor(Base):
    """A clinician practising at one or more clinics, performing one or more services."""

    __tablename__ = "doctors"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    gender: Mapped[str | None] = mapped_column(
        String(10), nullable=True, index=True
    )  # "F" | "M" | "other"
    specializations: Mapped[list[str]] = mapped_column(
        ARRAY(String(80)), nullable=False, server_default="{}"
    )
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    clinic_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("clinics.id", ondelete="SET NULL"), nullable=True, index=True
    )
    experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credentials: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, server_default="{}"
    )
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, server_default="{}"
    )
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    bio_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    bio_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_doctors_tenant_slug"),
        Index("idx_doctors_specializations", "specializations", postgresql_using="gin"),
    )


class ContentChunk(Base):
    """
    A chunk of website content (procedure pages, FAQs, comparisons) embedded
    for retrieval-augmented Q&A.
    """

    __tablename__ = "content_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, index=True
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="page"
    )  # page | faq | blog | comparison
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024), nullable=True
    )
    chunk_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source_url", "chunk_index",
            name="uq_content_chunks_source_chunk",
        ),
        Index("idx_content_chunks_metadata", "metadata", postgresql_using="gin"),
        Index(
            "idx_content_chunks_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
