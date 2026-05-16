"""Agent kernel + verticals.

The kernel lives in `app.agents.shared`. Each vertical (commerce, dental, ...)
lives under `app.agents.verticals.<name>` and registers itself with the
kernel registry on import.
"""
