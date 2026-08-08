"""Authentication helpers for API endpoints."""

import logging
import os
from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import jsonify, request

def get_auth_token() -> str | None:
    """Extract Bearer token from Authorization header or query param.

    Query-param fallback supports EventSource (SSE) streams which cannot set
    custom headers.  The returned token is still validated by
    ``verify_user_token()`` in ``require_auth``, so the ``user_id`` injected
    into route handlers is always authenticated — quota tracking is therefore
    unaffected by whether the token arrived via header or query param.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    # Fallback for SSE: token may be passed as query param.
    return request.args.get("token")


LOCAL_DEV_USER: dict[str, Any] = {
    "id": "local-dev-user",
    "email": "dev@localhost",
    "role": "admin",
    "status": "active",
    "daily_quota": 100,
    "used_quota": 0,
}


def is_local_dev_mode() -> bool:
    """Return True when local development bypass is active.

    Only explicit DISABLE_AUTH=1 is allowed. The previous auto bypass based on
    FLASK_DEBUG + missing SUPABASE_URL has been removed because it is too easy
    to enable accidentally in production.
    """
    return os.getenv("DISABLE_AUTH") == "1"


def require_auth(f: Callable) -> Callable:
    """Decorator to require valid Supabase auth token.

    Injects `user` dict into kwargs if valid.
    Returns 401 if missing or invalid.

    Local development bypass:
      Set DISABLE_AUTH=1 in the environment to skip token verification.
      This is ONLY for local dev/testing and must never be enabled in production.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        if is_local_dev_mode():
            kwargs["user"] = LOCAL_DEV_USER
            return f(*args, **kwargs)

        token = get_auth_token()
        if not token:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": {
                            "code": ErrorCode.UNAUTHORIZED.value,
                            "message": "Authorization header required.",
                            "retryable": False,
                        },
                    }
                ),
                401,
            )

        user = verify_user_token(token)
        if not user:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": {
                            "code": ErrorCode.UNAUTHORIZED.value,
                            "message": "Invalid or expired token.",
                            "retryable": False,
                        },
                    }
                ),
                401,
            )

        if user.get("status") != "active":
            return (
                jsonify(
                    {
                        "success": False,
                        "error": {
                            "code": ErrorCode.UNAUTHORIZED.value,
                            "message": "Account suspended.",
                            "retryable": False,
                        },
                    }
                ),
                403,
            )

        kwargs["user"] = user
        return f(*args, **kwargs)

    return wrapper


def check_quota(user_id: str, analysis_id: str, units: int = 1) -> tuple[bool, int, str | None]:
    """Reserve quota for analysis.

    Args:
        user_id: User UUID.
        analysis_id: Analysis UUID.
        units: Units to reserve.

    Returns:
        (success, remaining, ledger_id)
    """
    return reserve_user_quota(user_id, analysis_id, units)
