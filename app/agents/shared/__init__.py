"""Vertical-agnostic agent kernel.

Modules in this package are shared across all verticals (commerce, dental, etc.)
and must NOT import from any specific vertical. The dispatcher in `registry`
selects the right vertical at request time based on `tenant.vertical`.
"""
