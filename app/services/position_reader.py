"""Read user position configuration from Supabase profiles.

A standalone service — does not depend on the vibe orchestrator.
Used by the RSI trading plan builder to compute per-trade position size.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from app.infra.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def get_position_config(user_id: str) -> Optional[dict]:
    """Return ``{"position_config": ..., "position_balance": ...}`` or ``None``.

    Queries the Supabase ``profiles`` table with the service role so it
    works regardless of the caller's RLS context.

    Returns ``None`` when:
    - The Supabase client is unavailable.
    - The row does not exist or has no ``position_config`` / ``position_balance``.
    - Any query error occurs (logged and swallowed).
    """
    if not _supabase_available():
        return None
    try:
        client = get_supabase_client(use_service_role=True)
        result = (
            client.table("profiles")
            .select("position_config, position_balance")
            .eq("id", user_id)
            .single()
            .execute()
        )
        data = result.data or {}
        config = data.get("position_config")
        if config is None:
            return None
        return {"position_config": config, "position_balance": data.get("position_balance")}
    except Exception:
        logger.warning("Failed to load position config for user %s", user_id, exc_info=True)
        return None


def _supabase_available() -> bool:
    return bool(os.environ.get("SUPABASE_URL"))
