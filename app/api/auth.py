"""Authentication helpers for API endpoints."""
import logging
import os
from functools import wraps
from typing import Optional, Dict, Any, Callable
from flask import request, jsonify, current_app

from app.api.errors import AppError
from app.domain.enums import ErrorCode
from app.infra.supabase_client import (
    verify_user_token,
    reserve_user_quota,
    release_ledger_quota,
    create_analysis_record,
    update_analysis_record,
    upload_chart,
    get_chart_url,
    log_audit_event,
)

logger = logging.getLogger(__name__)


def get_auth_token() -> Optional[str]:
    """Extract Bearer token from Authorization header or query param.

    Query-param fallback supports EventSource which cannot set headers.
    Returns:
        Token string or None.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    # Fallback for SSE: token may be passed as query param.
    return request.args.get("token")


LOCAL_DEV_USER: Dict[str, Any] = {
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
            return jsonify({
                "success": False,
                "error": {
                    "code": ErrorCode.UNAUTHORIZED.value,
                    "message": "Authorization header required.",
                    "retryable": False,
                }
            }), 401

        user = verify_user_token(token)
        if not user:
            return jsonify({
                "success": False,
                "error": {
                    "code": ErrorCode.UNAUTHORIZED.value,
                    "message": "Invalid or expired token.",
                    "retryable": False,
                }
            }), 401

        if user.get("status") != "active":
            return jsonify({
                "success": False,
                "error": {
                    "code": ErrorCode.UNAUTHORIZED.value,
                    "message": "Account suspended.",
                    "retryable": False,
                }
            }), 403

        kwargs["user"] = user
        return f(*args, **kwargs)
    return wrapper


def check_quota(user_id: str, analysis_id: str, units: int = 1) -> tuple[bool, int, Optional[str]]:
    """Reserve quota for analysis.

    Args:
        user_id: User UUID.
        analysis_id: Analysis UUID.
        units: Units to reserve.

    Returns:
        (success, remaining, ledger_id)
    """
    return reserve_user_quota(user_id, analysis_id, units)
