"""
Shared Pydantic validators for LLM structured output models.

LLMs sometimes return JSON-serialized strings instead of native types
(e.g. '{"key": "val"}' instead of {"key": "val"}). These validators
normalise the values before Pydantic's own type checking runs.
"""

import json
from typing import Any, Dict, List


def parse_dict(v: Any) -> Dict[str, Any]:
    """Accept a JSON string and return a dict, or pass through a dict."""
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return {}
    return v  # let Pydantic raise if it's something else entirely


def parse_list(v: Any) -> List[Any]:
    """Accept a JSON string and return a list, or pass through a list."""
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return []
    return v


def parse_bool(v: Any) -> bool:
    """Accept common string representations of booleans."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        if v.lower() in ("true", "1", "yes"):
            return True
        if v.lower() in ("false", "0", "no"):
            return False
    return v


def parse_literal_lower(v: Any) -> Any:
    """Lowercase a string so case-insensitive Literal matching works."""
    if isinstance(v, str):
        return v.lower().strip()
    return v
