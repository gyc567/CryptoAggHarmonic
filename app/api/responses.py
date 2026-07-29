"""Unified JSON response envelope for API routes.

All non-SSE endpoints return one of two shapes:

    success: { "success": true,  "data": <object> }
    error:   { "success": false, "error": { code, message, retryable, request_id? } }

This keeps the wire contract identical across the legacy ``app/main.py``
endpoints, the Vibe blueprint and the trend-RSI blueprint, and gives the
frontend a single parser rule (`"error" in res ? ... : res.data`) instead
of one branch per endpoint.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from flask import jsonify

from app.domain.vibe_schemas import VibeErrorDetail

logger = logging.getLogger(__name__)


def success(data: Any) -> tuple[Any, int]:
    """Wrap a success payload in the standard envelope."""
    return jsonify({"success": True, "data": data}), 200


def error(
    code: str,
    message: str,
    status: int = 400,
    retryable: bool = False,
    request_id: Optional[str] = None,
) -> tuple[Any, int]:
    """Wrap an error detail in the standard envelope."""
    return (
        jsonify(
            {
                "success": False,
                "error": VibeErrorDetail(
                    code=code,
                    message=message,
                    retryable=retryable,
                    request_id=request_id,
                ).model_dump(exclude_none=False),
            }
        ),
        status,
    )
