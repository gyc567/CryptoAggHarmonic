"""Tests for the admin API routes (invite code and user management).

These tests use the Flask test client with mocked Supabase responses
and DISABLE_AUTH=1 to bypass auth checks.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, PropertyMock
import pytest
from flask import Flask


# ── Helper to build chainable mock queries ──────────────────────────────────


def make_query_mock(data, count=None):
    """Create a chainable mock that ends with execute() returning data/count."""

    class _Chain:
        def __init__(self, _data, _count=None):
            self._data = _data
            self._count = _count

        def select(self, *args, **kwargs):
            return self

        def eq(self, *args, **kwargs):
            return self

        def order(self, *args, **kwargs):
            return self

        def range(self, *args, **kwargs):
            return self

        def update(self, *args, **kwargs):
            return self

        def single(self, *args, **kwargs):
            return self

        def execute(self, *args, **kwargs):
            class Result:
                data = self._data
                count = self._count

            return Result()

    return _Chain(data, count)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def app():
    """Build a minimal Flask app with admin blueprint registered."""
    from app.api.admin_routes import admin_bp

    app = Flask(__name__)
    app.register_blueprint(admin_bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ── Admin required decorator tests ──────────────────────────────────────────


class TestAdminRequiredDecorator:
    """Tests for the _admin_required decorator logic."""

    def test_non_admin_returns_403(self, app):
        """A user with role='user' should get 403 on admin endpoints."""
        from app.api.admin_routes import _admin_required

        @_admin_required
        def mock_handler(user=None):
            return {"ok": True}

        regular = {
            "id": "user-uuid",
            "email": "user@example.com",
            "role": "user",
            "status": "active",
            "daily_quota": 5,
        }

        with app.app_context():
            wrapper = _admin_required(mock_handler)
            response, status_code = wrapper(user=regular)
            assert status_code == 403

    def test_admin_passes_through(self, app):
        """A user with role='admin' should pass through the decorator."""
        from app.api.admin_routes import _admin_required

        @_admin_required
        def mock_handler(user=None):
            return {"ok": True, "user_id": user["id"]}

        admin = {
            "id": "admin-uuid",
            "email": "admin@example.com",
            "role": "admin",
            "status": "active",
            "daily_quota": 100,
        }

        with app.app_context():
            wrapper = _admin_required(mock_handler)
            result = wrapper(user=admin)
            assert isinstance(result, dict)
            assert result == {"ok": True, "user_id": "admin-uuid"}

    def test_missing_user_returns_401(self, app):
        """Missing user returns 401."""
        from app.api.admin_routes import _admin_required

        @_admin_required
        def mock_handler(user=None):
            return {"ok": True}

        with app.app_context():
            wrapper = _admin_required(mock_handler)
            response, status_code = wrapper(user=None)
            assert status_code == 401


# ── Create invite tests ─────────────────────────────────────────────────────


class TestCreateInvite:
    """Tests for POST /api/admin/invites."""

    @patch.dict(os.environ, {"DISABLE_AUTH": "1"})
    @patch("app.api.admin_routes.get_supabase_client")
    def test_creates_invite_with_default_quota(self, mock_get_client, app, client):
        """POST /api/admin/invites creates an invite code."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value.data = [
            {"id": "invite-uuid", "code": "ABC12345", "quota": 5}
        ]

        with patch("app.api.admin_routes.log_audit_event"):
            resp = client.post(
                "/api/admin/invites",
                json={"email": "test@example.com"},
            )

        assert resp.status_code == 201
        data = resp.get_json()
        assert data["success"] is True
        assert data["data"]["code"] == "ABC12345"
        assert data["data"]["quota"] == 5

    @patch.dict(os.environ, {"DISABLE_AUTH": "1"})
    @patch("app.api.admin_routes.get_supabase_client")
    def test_creates_invite_with_custom_quota(self, mock_get_client, app, client):
        """POST /api/admin/invites respects quota and rsi_quota parameters."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value.data = [
            {"id": "invite-uuid", "code": "XYZ99999", "quota": 20}
        ]

        with patch("app.api.admin_routes.log_audit_event"):
            resp = client.post(
                "/api/admin/invites",
                json={"quota": 20, "rsi_quota": 100, "max_uses": 5},
            )

        assert resp.status_code == 201
        data = resp.get_json()
        assert data["success"] is True
        assert data["data"]["quota"] == 20

    @patch.dict(os.environ, {"DISABLE_AUTH": "1"})
    @patch("app.api.admin_routes.get_supabase_client")
    def test_create_invite_rpc_failure_returns_500(self, mock_get_client, app, client):
        """RPC failure returns 500."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value.data = None

        resp = client.post(
            "/api/admin/invites",
            json={},
        )

        assert resp.status_code == 500
        data = resp.get_json()
        assert data["success"] is False

    @patch.dict(os.environ, {"DISABLE_AUTH": "1"})
    def test_disable_auth_bypasses_auth_check(self, app, client):
        """With DISABLE_AUTH=1, even no token passes through to handler."""
        resp = client.post(
            "/api/admin/invites",
            json={},
        )
        # Should NOT be 401 since DISABLE_AUTH=1 bypasses auth
        assert resp.status_code != 401


# ── List invites tests ─────────────────────────────────────────────────────


class TestListInvites:
    """Tests for GET /api/admin/invites."""

    @patch.dict(os.environ, {"DISABLE_AUTH": "1"})
    @patch("app.api.admin_routes.get_supabase_client")
    def test_lists_invites_paginated(self, mock_get_client, app, client):
        """GET /api/admin/invites returns paginated list."""
        invite_data = [
            {
                "id": "invite-1",
                "code": "CODE11111",
                "email": "test1@example.com",
                "status": "pending",
                "daily_quota_override": 5,
                "rsi_daily_quota_override": 50,
                "used_count": 0,
                "max_uses": 1,
                "expires_at": "2026-09-20T00:00:00Z",
                "created_at": "2026-09-10T00:00:00Z",
                "created_by": "admin-uuid",
            },
        ]

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Track call count to return different mocks for list vs count query
        call_count = [0]

        def table_side_effect(table_name):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: list query
                return make_query_mock(invite_data)
            else:
                # Second call: count query
                return make_query_mock([], count=1)

        mock_client.table.side_effect = table_side_effect

        resp = client.get("/api/admin/invites")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["data"]["items"]) == 1
        assert data["data"]["items"][0]["code"] == "CODE11111"
        assert data["data"]["items"][0]["quota"] == 5

    @patch.dict(os.environ, {"DISABLE_AUTH": "1"})
    @patch("app.api.admin_routes.get_supabase_client")
    def test_lists_invites_with_status_filter(self, mock_get_client, app, client):
        """GET /api/admin/invites?status=pending filters correctly."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        call_count = [0]

        def table_side_effect(table_name):
            call_count[0] += 1
            if call_count[0] == 1:
                return make_query_mock([])
            else:
                return make_query_mock([], count=0)

        mock_client.table.side_effect = table_side_effect

        resp = client.get("/api/admin/invites?status=pending")

        assert resp.status_code == 200


# ── Revoke invite tests ─────────────────────────────────────────────────────


class TestRevokeInvite:
    """Tests for DELETE /api/admin/invites/:id."""

    @patch.dict(os.environ, {"DISABLE_AUTH": "1"})
    @patch("app.api.admin_routes.get_supabase_client")
    def test_revokes_invite_successfully(self, mock_get_client, app, client):
        """DELETE /api/admin/invites/:id marks invite as revoked."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        call_count = [0]

        def table_side_effect(table_name):
            call_count[0] += 1
            if call_count[0] == 1:
                # Check: returns invite data
                return make_query_mock({"id": "invite-uuid"})
            else:
                # Update: returns None
                return make_query_mock(None)

        mock_client.table.side_effect = table_side_effect

        with patch("app.api.admin_routes.log_audit_event"):
            resp = client.delete("/api/admin/invites/invite-uuid")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    @patch.dict(os.environ, {"DISABLE_AUTH": "1"})
    @patch("app.api.admin_routes.get_supabase_client")
    def test_revokes_nonexistent_returns_404(self, mock_get_client, app, client):
        """DELETE /api/admin/invites/:id returns 404 for unknown id."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Check returns empty
        mock_client.table.return_value = make_query_mock(None)

        resp = client.delete("/api/admin/invites/nonexistent-uuid")

        assert resp.status_code == 404


# ── List users tests ────────────────────────────────────────────────────────


class TestListUsers:
    """Tests for GET /api/admin/users."""

    @patch.dict(os.environ, {"DISABLE_AUTH": "1"})
    @patch("app.api.admin_routes.get_supabase_client")
    def test_lists_users_paginated(self, mock_get_client, app, client):
        """GET /api/admin/users returns paginated user list."""
        user_data = [
            {
                "id": "user-1",
                "email": "user1@example.com",
                "role": "user",
                "status": "active",
                "daily_quota": 5,
                "rsi_daily_quota": 50,
                "invited_by": None,
                "created_at": "2026-09-01T00:00:00Z",
                "total_analyses": 10,
            },
        ]

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # RPC call for user list
        mock_client.rpc.return_value.execute.return_value.data = user_data

        # Table call for count
        mock_client.table.return_value = make_query_mock([], count=1)

        resp = client.get("/api/admin/users")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["data"]["items"]) == 1
        assert data["data"]["items"][0]["email"] == "user1@example.com"
        assert data["data"]["items"][0]["total_analyses"] == 10


# ── Update user tests ─────────────────────────────────────────────────────


class TestUpdateUser:
    """Tests for PATCH /api/admin/users/:id."""

    @patch.dict(os.environ, {"DISABLE_AUTH": "1"})
    @patch("app.api.admin_routes.get_supabase_client")
    def test_updates_user_quota(self, mock_get_client, app, client):
        """PATCH /api/admin/users/:id updates daily_quota."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        call_count = [0]

        def table_side_effect(table_name):
            call_count[0] += 1
            if call_count[0] == 1:
                # Check user exists
                return make_query_mock({"id": "user-uuid"})
            else:
                # Update
                return make_query_mock(None)

        mock_client.table.side_effect = table_side_effect

        with patch("app.api.admin_routes.log_audit_event"):
            resp = client.patch(
                "/api/admin/users/user-uuid",
                json={"daily_quota": 20, "rsi_daily_quota": 100},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    @patch.dict(os.environ, {"DISABLE_AUTH": "1"})
    @patch("app.api.admin_routes.get_supabase_client")
    def test_updates_user_status_to_suspended(self, mock_get_client, app, client):
        """PATCH can suspend a user."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        call_count = [0]

        def table_side_effect(table_name):
            call_count[0] += 1
            if call_count[0] == 1:
                return make_query_mock({"id": "user-uuid"})
            else:
                return make_query_mock(None)

        mock_client.table.side_effect = table_side_effect

        with patch("app.api.admin_routes.log_audit_event"):
            resp = client.patch(
                "/api/admin/users/user-uuid",
                json={"status": "suspended"},
            )

        assert resp.status_code == 200

    @patch.dict(os.environ, {"DISABLE_AUTH": "1"})
    def test_update_user_no_valid_fields_returns_400(self, app, client):
        """PATCH with no valid fields returns 400."""
        resp = client.patch(
            "/api/admin/users/user-uuid",
            json={"invalid_field": "value"},
        )

        assert resp.status_code == 400

    @patch.dict(os.environ, {"DISABLE_AUTH": "1"})
    @patch("app.api.admin_routes.get_supabase_client")
    def test_update_nonexistent_user_returns_404(self, mock_get_client, app, client):
        """PATCH for unknown user returns 404."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Check returns empty (user not found)
        mock_client.table.return_value = make_query_mock(None)

        resp = client.patch(
            "/api/admin/users/nonexistent-uuid",
            json={"daily_quota": 10},
        )

        assert resp.status_code == 404
