"""Vertical registry and dispatcher.

The registry is the single seam between the kernel and the verticals. Each
vertical registers itself by name; `get_vertical(name)` is how the chat
route reaches the right agent graph.

Verticals register at import time. We import them here (not in the kernel
modules) so the import graph stays one-way: kernel -> registry -> verticals.
"""

from __future__ import annotations

from app.agents.shared.vertical import Vertical


_REGISTRY: dict[str, Vertical] = {}


def register(vertical: Vertical) -> None:
    """Register a vertical implementation under its `name`."""
    if vertical.name in _REGISTRY:
        raise ValueError(f"Vertical already registered: {vertical.name}")
    _REGISTRY[vertical.name] = vertical


def get_vertical(name: str) -> Vertical:
    """Look up a vertical by name. Raises if not registered."""
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise ValueError(
            f"Unknown vertical: {name!r}. Registered verticals: {known}"
        )


def registered_verticals() -> list[str]:
    """Names of all currently registered verticals (for diagnostics)."""
    return sorted(_REGISTRY)


def _bootstrap() -> None:
    """Import vertical modules so they self-register.

    Called once at app startup (from the FastAPI lifespan). Importing here
    avoids circular imports: verticals depend on shared primitives, not the
    other way around.
    """
    # Commerce vertical wraps the existing ConsultationGraph.
    from app.agents.verticals.commerce.vertical import CommerceVertical  # noqa: F401

    if "commerce" not in _REGISTRY:
        register(CommerceVertical())


_bootstrap()
