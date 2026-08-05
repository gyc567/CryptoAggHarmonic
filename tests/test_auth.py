"""Tests for API auth helpers and main.py endpoints."""

import os
from unittest.mock import patch

import pytest
from flask import Flask

from app.api.auth import (
    LOCAL_DEV_USER,
    check_quota,
    get_auth_token,
    require_auth,
)
from app.domain.enums import ErrorCode


# Create minimal Flask app for testing
@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestGetAuthToken:
    def test_valid_bearer(self, app, client):
        with app.test_request_context(headers={"Authorization": "Bearer test-token-123"}):
            result = get_auth_token()
            assert result == "test-token-123"

    def test_missing_header(self, app, client):
        with app.test_request_context():
            result = get_auth_token()
            assert result is None

    def test_invalid_format_no_bearer(self, app, client):
        with app.test_request_context(headers={"Authorization": "Basic dXNlcjpwYXNz"}):
            result = get_auth_token()
            assert result is None

    def test_empty_header(self, app, client):
        with app.test_request_context(headers={"Authorization": ""}):
            result = get_auth_token()
            assert result is None


class TestRequireAuthDecorator:
    @patch.dict(os.environ, {"DISABLE_AUTH": ""}, clear=True)
    @patch("app.api.auth.verify_user_token")
    @patch("app.api.auth.get_auth_token")
    def test_valid_token(self, mock_get_token, mock_verify, app, client):
        mock_get_token.return_value = "valid-token"
        mock_verify.return_value = {
            "id": "user-123",
            "email": "test@example.com",
            "role": "user",
            "status": "active",
            "daily_quota": 5,
        }

        @app.route("/test-auth")
        @require_auth
        def handler(user=None):
            return {"user_id": user["id"]}

        with app.test_client() as c:
            resp = c.get("/test-auth", headers={"Authorization": "Bearer valid-token"})
            assert resp.status_code == 200
            assert resp.get_json() == {"user_id": "user-123"}

    @patch("app.api.auth.get_auth_token")
    def test_missing_header(self, mock_get_token, app, client):
        mock_get_token.return_value = None

        @app.route("/test-auth")
        @require_auth
        def handler(user=None):
            return {"ok": True}

        with app.test_client() as c:
            resp = c.get("/test-auth")
            assert resp.status_code == 401
            data = resp.get_json()
            assert data["success"] is False
            assert data["error"]["code"] == ErrorCode.UNAUTHORIZED.value

    @patch.dict(os.environ, {"DISABLE_AUTH": ""}, clear=True)
    @patch("app.api.auth.verify_user_token")
    @patch("app.api.auth.get_auth_token")
    def test_invalid_token(self, mock_get_token, mock_verify, app, client):
        mock_get_token.return_value = "invalid-token"
        mock_verify.return_value = None

        @app.route("/test-auth")
        @require_auth
        def handler(user=None):
            return {"ok": True}

        with app.test_client() as c:
            resp = c.get("/test-auth", headers={"Authorization": "Bearer invalid-token"})
            assert resp.status_code == 401

    @patch.dict(os.environ, {"DISABLE_AUTH": ""}, clear=True)
    @patch("app.api.auth.verify_user_token")
    @patch("app.api.auth.get_auth_token")
    def test_suspended_user(self, mock_get_token, mock_verify, app, client):
        mock_get_token.return_value = "valid-token"
        mock_verify.return_value = {
            "id": "user-123",
            "email": "test@example.com",
            "role": "user",
            "status": "suspended",
            "daily_quota": 5,
        }

        @app.route("/test-auth")
        @require_auth
        def handler(user=None):
            return {"ok": True}

        with app.test_client() as c:
            resp = c.get("/test-auth", headers={"Authorization": "Bearer valid-token"})
            assert resp.status_code == 403
            data = resp.get_json()
            assert data["error"]["message"] == "Account suspended."


class TestRequireAuthBypass:
    def test_disable_auth_env_bypass(self, app, client):
        @app.route("/test-auth")
        @require_auth
        def handler(user=None):
            return {"user_id": user["id"]}

        with patch.dict(os.environ, {"DISABLE_AUTH": "1"}, clear=False):
            with app.test_client() as c:
                resp = c.get("/test-auth")
                assert resp.status_code == 200
                assert resp.get_json() == {"user_id": LOCAL_DEV_USER["id"]}

    def test_no_auto_dev_bypass_when_debug_and_no_supabase_url(self, app, client):
        """Auto bypass based on FLASK_DEBUG + missing SUPABASE_URL is removed."""

        @app.route("/test-auth")
        @require_auth
        def handler(user=None):
            return {"ok": True}

        app.debug = True
        env_patch = {"SUPABASE_URL": "", "DISABLE_AUTH": ""}
        with patch.dict(os.environ, env_patch, clear=False):
            with app.test_client() as c:
                resp = c.get("/test-auth")
                assert resp.status_code == 401

    def test_explicit_disable_auth_bypass(self, app, client):
        @app.route("/test-auth")
        @require_auth
        def handler(user=None):
            return {"user_id": user["id"]}

        env_patch = {"DISABLE_AUTH": "1"}
        with patch.dict(os.environ, env_patch, clear=False):
            with app.test_client() as c:
                resp = c.get("/test-auth")
                assert resp.status_code == 200
                assert resp.get_json() == {"user_id": LOCAL_DEV_USER["id"]}


class TestCheckQuota:
    @patch("app.api.auth.reserve_user_quota")
    def test_quota_available(self, mock_reserve):
        mock_reserve.return_value = (True, 4, "ledger-123")
        success, remaining, ledger_id = check_quota("user-123", "analysis-456", 1)
        assert success is True
        assert remaining == 4
        assert ledger_id == "ledger-123"

    @patch("app.api.auth.reserve_user_quota")
    def test_quota_exceeded(self, mock_reserve):
        mock_reserve.return_value = (False, 0, None)
        success, remaining, ledger_id = check_quota("user-123", "analysis-456", 1)
        assert success is False
        assert remaining == 0
        assert ledger_id is None
