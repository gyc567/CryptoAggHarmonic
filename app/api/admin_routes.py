"""Admin API endpoints for invite code and user management.

Routes:
- POST   /api/admin/invites          - Create invite code
- GET    /api/admin/invites          - List invite codes
- DELETE /api/admin/invites/:id      - Revoke invite code
- GET    /api/admin/users            - List users (paginated)
- GET    /api/admin/users/:id        - Get user details
- PATCH  /api/admin/users/:id        - Update user (quota/status/role)
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from app.api.auth import require_auth
from app.api.rate_limit import get_limiter
from app.domain.enums import ErrorCode
from app.infra.supabase_client import (
    get_supabase_client,
    get_user_profile,
    list_user_analyses,
    log_audit_event,
)

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _admin_required(f):
    """Decorator: require admin role. Must be applied after @require_auth."""
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        # `user` is injected by @require_auth as the first kwarg
        user = kwargs.get("user")
        if not user:
            return jsonify({
                "success": False,
                "error": {
                    "code": ErrorCode.UNAUTHORIZED.value,
                    "message": "Authentication required.",
                    "retryable": False,
                }
            }), 401

        if user.get("role") != "admin":
            return jsonify({
                "success": False,
                "error": {
                    "code": ErrorCode.FORBIDDEN.value,
                    "message": "Admin access required.",
                    "retryable": False,
                }
            }), 403

        return f(*args, **kwargs)

    return wrapper


# =============================================================================
# Invite Code Management
# =============================================================================

@admin_bp.route("/invites", methods=["POST"])
@require_auth
@_admin_required
@get_limiter().limit("admin")
def create_invite(user: dict[str, Any]):
    """Create a new invite code.

    Body (JSON):
        email: str (optional) - pre-assign to specific email
        quota: int (default 5) - daily analysis quota (max 1000)
        rsi_quota: int (default 50) - daily RSI quota (max 10000)
        max_uses: int (default 1) - how many times code can be used (max 100)
        days_valid: int (default 7) - how many days until expiry (max 365)

    Returns:
        201: {"success": true, "data": {"id", "code", "quota"}}
        400: Invalid params
        403: Not admin
        429: Rate limit exceeded (max 10/min for admin operations)
        500: Creation failed
    """
    data = request.get_json(silent=True) or {}

    email = data.get("email")
    quota = max(1, min(data.get("quota", 5), 1000))  # Clamp to 1-1000
    rsi_quota = max(1, min(data.get("rsi_quota", 50), 10000))
    max_uses = max(1, min(data.get("max_uses", 1), 100))  # Clamp to 1-100
    days_valid = max(1, min(data.get("days_valid", 7), 365))

    try:
        # Safe: service role bypasses RLS, but this route is admin-only
        # and requires a valid admin JWT via @require_auth + @_admin_required.
        client = get_supabase_client(use_service_role=True)
        result = client.rpc("create_invite_code", {
            "p_email": email,
            "p_quota": quota,
            "p_rsi_quota": rsi_quota,
            "p_max_uses": max_uses,
            "p_created_by": user["id"],
            "p_days_valid": days_valid,
        }).execute()

        if not result.data:
            return jsonify({
                "success": False,
                "error": {
                    "code": "CREATE_FAILED",
                    "message": "Failed to create invite code.",
                    "retryable": True,
                }
            }), 500

        row = result.data[0]

        log_audit_event(
            actor_id=user["id"],
            action="invite_created",
            target_type="invite",
            target_id=row["id"],
            details={
                "code": row["code"],
                "quota": quota,
                "rsi_quota": rsi_quota,
                "max_uses": max_uses,
                "days_valid": days_valid,
            }
        )

        return jsonify({
            "success": True,
            "data": {
                "id": row["id"],
                "code": row["code"],
                "quota": row["quota"],
                "rsi_quota": rsi_quota,
                "max_uses": max_uses,
                "days_valid": days_valid,
            }
        }), 201

    except Exception:
        logger.exception("Failed to create invite code")
        return jsonify({
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Failed to create invite code.",
                "retryable": True,
            }
        }), 500


@admin_bp.route("/invites", methods=["GET"])
@require_auth
@_admin_required
def list_invites(user: dict[str, Any]):
    """List all invite codes.

    Query params:
        status: str (optional) - filter by status (pending/accepted/revoked/expired)
        limit: int (default 100, max 500)
        offset: int (default 0)

    Returns:
        200: {"success": true, "data": {"items": [...], "total": int}}
    """
    status_filter = request.args.get("status")
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = int(request.args.get("offset", 0))

    try:
        client = get_supabase_client(use_service_role=True)

        query = client.table("invites").select("*").order("created_at", desc=True)

        if status_filter:
            query = query.eq("status", status_filter)

        result = query.range(offset, offset + limit - 1).execute()

        items = []
        for row in (result.data or []):
            items.append({
                "id": row["id"],
                "email": row.get("email"),
                "code": row.get("code"),
                "status": row["status"],
                "quota": row.get("daily_quota_override", 5),
                "rsi_quota": row.get("rsi_daily_quota_override", 50),
                "used_count": row.get("used_count", 0),
                "max_uses": row.get("max_uses", 1),
                "expires_at": row.get("expires_at"),
                "created_at": row.get("created_at"),
                "created_by": row.get("created_by"),
            })

        # Get total count for pagination
        count_query = client.table("invites").select("id", count="exact")
        if status_filter:
            count_query = count_query.eq("status", status_filter)
        count_result = count_query.execute()

        return jsonify({
            "success": True,
            "data": {
                "items": items,
                "total": count_result.count or 0,
                "limit": limit,
                "offset": offset,
            }
        })

    except Exception:
        logger.exception("Failed to list invites")
        return jsonify({
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Failed to list invite codes.",
                "retryable": True,
            }
        }), 500


@admin_bp.route("/invites/<invite_id>", methods=["DELETE"])
@require_auth
@_admin_required
def revoke_invite(user: dict[str, Any], invite_id: str):
    """Revoke an invite code.

    Returns:
        200: {"success": true}
        403: Not admin
        404: Invite not found
    """
    try:
        client = get_supabase_client(use_service_role=True)

        # Check invite exists
        check = client.table("invites").select("id").eq("id", invite_id).single().execute()
        if not check.data:
            return jsonify({
                "success": False,
                "error": {
                    "code": ErrorCode.NOT_FOUND.value,
                    "message": "Invite not found.",
                    "retryable": False,
                }
            }), 404

        # Update status to revoked
        client.table("invites").update({"status": "revoked"}).eq("id", invite_id).execute()

        log_audit_event(
            actor_id=user["id"],
            action="invite_revoked",
            target_type="invite",
            target_id=invite_id,
        )

        return jsonify({"success": True})

    except Exception:
        logger.exception("Failed to revoke invite")
        return jsonify({
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Failed to revoke invite code.",
                "retryable": True,
            }
        }), 500


# =============================================================================
# User Management
# =============================================================================

@admin_bp.route("/users", methods=["GET"])
@require_auth
@_admin_required
def list_users(user: dict[str, Any]):
    """List all users (paginated).

    Query params:
        page: int (default 1)
        limit: int (default 20, max 100)

    Returns:
        200: {"success": true, "data": {"items": [...], "total": int, "page": int}}
    """
    page = max(1, int(request.args.get("page", 1)))
    limit = min(max(1, int(request.args.get("limit", 20))), 100)
    offset = (page - 1) * limit

    try:
        client = get_supabase_client(use_service_role=True)

        # Get profiles with analysis count using RPC
        result = client.rpc("list_users", {
            "p_limit": limit,
            "p_offset": offset,
        }).execute()

        items = []
        for row in (result.data or []):
            items.append({
                "id": row["id"],
                "email": row["email"],
                "role": row["role"],
                "status": row["status"],
                "daily_quota": row["daily_quota"],
                "rsi_daily_quota": row["rsi_daily_quota"],
                "invited_by": row.get("invited_by"),
                "created_at": row["created_at"],
                "total_analyses": row["total_analyses"],
            })

        # Get total count
        count_result = client.table("profiles").select("id", count="exact").execute()

        return jsonify({
            "success": True,
            "data": {
                "items": items,
                "total": count_result.count or 0,
                "page": page,
                "limit": limit,
            }
        })

    except Exception:
        logger.exception("Failed to list users")
        return jsonify({
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Failed to list users.",
                "retryable": True,
            }
        }), 500


@admin_bp.route("/users/<user_id>", methods=["GET"])
@require_auth
@_admin_required
def get_user(user: dict[str, Any], user_id: str):
    """Get user details with recent analyses.

    Returns:
        200: {"success": true, "data": {profile + recent_analyses}}
        403: Not admin
        404: User not found
    """
    try:
        client = get_supabase_client(use_service_role=True)

        profile = client.table("profiles").select("*").eq("id", user_id).single().execute()
        if not profile.data:
            return jsonify({
                "success": False,
                "error": {
                    "code": ErrorCode.NOT_FOUND.value,
                    "message": "User not found.",
                    "retryable": False,
                }
            }), 404

        # Get recent analyses
        analyses = list_user_analyses(user_id, limit=10)

        return jsonify({
            "success": True,
            "data": {
                **profile.data,
                "recent_analyses": analyses,
            }
        })

    except Exception:
        logger.exception("Failed to get user")
        return jsonify({
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Failed to get user details.",
                "retryable": True,
            }
        }), 500


@admin_bp.route("/users/<user_id>", methods=["PATCH"])
@require_auth
@_admin_required
def update_user(user: dict[str, Any], user_id: str):
    """Update user (quota, status, role).

    Body (JSON):
        daily_quota: int (optional) - new daily analysis quota
        rsi_daily_quota: int (optional) - new daily RSI quota
        status: str (optional) - "active" or "suspended"
        role: str (optional) - "user" or "admin"

    Returns:
        200: {"success": true, "data": {updated fields}}
        400: No valid fields
        403: Not admin
        404: User not found
    """
    data = request.get_json(silent=True) or {}

    # Validate and sanitize inputs
    allowed_fields = {"daily_quota", "rsi_daily_quota", "status", "role"}
    updates: dict[str, Any] = {}

    if "daily_quota" in data:
        updates["daily_quota"] = max(1, min(int(data["daily_quota"]), 10000))
    if "rsi_daily_quota" in data:
        updates["rsi_daily_quota"] = max(1, min(int(data["rsi_daily_quota"]), 100000))
    if "status" in data and data["status"] in ("active", "suspended"):
        updates["status"] = data["status"]
    if "role" in data and data["role"] in ("user", "admin"):
        updates["role"] = data["role"]

    if not updates:
        return jsonify({
            "success": False,
            "error": {
                "code": ErrorCode.INVALID_PARAMS.value,
                "message": "No valid fields to update.",
                "retryable": False,
            }
        }), 400

    try:
        client = get_supabase_client(use_service_role=True)

        # Check user exists
        check = client.table("profiles").select("id").eq("id", user_id).single().execute()
        if not check.data:
            return jsonify({
                "success": False,
                "error": {
                    "code": ErrorCode.NOT_FOUND.value,
                    "message": "User not found.",
                    "retryable": False,
                }
            }), 404

        # Update user
        client.table("profiles").update(updates).eq("id", user_id).execute()

        log_audit_event(
            actor_id=user["id"],
            action="user_updated",
            target_type="user",
            target_id=user_id,
            details=updates,
        )

        return jsonify({"success": True, "data": updates})

    except Exception:
        logger.exception("Failed to update user")
        return jsonify({
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Failed to update user.",
                "retryable": True,
            }
        }), 500
