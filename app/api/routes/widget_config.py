"""Public widget config endpoint.

Returns the per-tenant theme/branding for the embedded chat widget.
Unauthenticated, keyed by `?client_id=...`. The Origin header is checked
against the client's `allowed_origins` in DynamoDB to prevent arbitrary
sites from impersonating a tenant's branding.
"""

import logging
import os
from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widget", tags=["widget"])

TABLE_NAME = os.environ.get("WIDGET_CLIENTS_TABLE", "CurateAI-WidgetClients")
REGION = os.environ.get("WIDGET_CLIENTS_REGION", "us-east-1")


@lru_cache(maxsize=1)
def _table():
    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


@router.get("/config")
async def get_widget_config(
    request: Request,
    client_id: str = Query(..., min_length=1, max_length=128),
) -> dict[str, Any]:
    """Return the theme/branding configured for `client_id`.

    Response shape: `{"theme": {...}}` where `theme` is a JSON object the
    widget merges over its local config (backend overrides local). Returns
    `{"theme": {}}` when the client has no theme configured.
    """
    try:
        response = _table().get_item(Key={"client_id": client_id})
    except (BotoCoreError, ClientError) as e:
        logger.error("DynamoDB error fetching widget client %s: %s", client_id, e)
        raise HTTPException(status_code=502, detail="Config lookup failed")

    item = response.get("Item")
    if not item or not item.get("is_active", True):
        raise HTTPException(status_code=404, detail="Client not found")

    allowed_origins = item.get("allowed_origins") or []
    origin = request.headers.get("origin")
    if allowed_origins and "*" not in allowed_origins:
        if origin and origin not in allowed_origins:
            raise HTTPException(status_code=403, detail="Origin not allowed")

    theme = item.get("theme") or {}
    if not isinstance(theme, dict):
        logger.warning("Widget client %s has non-dict theme; ignoring", client_id)
        theme = {}

    return {"theme": theme}
