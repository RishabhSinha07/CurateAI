"""Polymorphic response schema returned by /chat.

Items are tagged with a `type` discriminator so a single response can carry
products, services, doctors, comparisons, etc. — whichever shapes the active
vertical produces. The kernel never inspects item contents; verticals build
items and frontends render them via a card registry keyed on `type`.

`vertical_context` is an opaque bag of per-vertical metadata that the kernel
neither reads nor writes (currently: commerce stuffs domain_slug, intent_type,
journey info there; dental will use it for its own state).
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class ChatItem(BaseModel):
    """A single result item the agent surfaces to the user."""

    type: str = Field(
        ...,
        description=(
            "Discriminator the frontend uses to pick a card component "
            "(e.g. 'product', 'service', 'doctor', 'comparison', 'stack')."
        ),
    )
    id: str
    title: str
    subtitle: str | None = None
    price: float | None = None
    currency: str = "USD"
    image_url: str | None = None
    url: str | None = None
    description: str | None = None
    badges: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class CtaLink(BaseModel):
    """A call-to-action button rendered in the response footer."""

    label: str
    url: str
    kind: str = Field(default="primary", description="'primary' | 'secondary'")


class ChatResponse(BaseModel):
    """The wire shape returned by POST /chat."""

    session_id: uuid.UUID
    response: str
    status: str
    items: list[ChatItem] = Field(default_factory=list)
    cta_links: list[CtaLink] = Field(default_factory=list)
    suggested_replies: list[str] = Field(default_factory=list)
    vertical_context: dict[str, Any] = Field(default_factory=dict)
