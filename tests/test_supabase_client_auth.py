"""Tests for new auth-related functions in supabase_client.py.

Tests the new helper functions for invite code management and user management.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest


class TestCreateInviteCode:
    """Tests for create_invite_code helper."""

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_returns_invite_data_on_success(self, mock_get_client):
        """create_invite_code returns id, code, quota on success."""
        from app.infra.supabase_client import create_invite_code

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value.data = [
            {"id": "invite-uuid", "code": "ABC12345", "quota": 20}
        ]

        result = create_invite_code(
            email="test@example.com",
            quota=20,
            rsi_quota=100,
            max_uses=5,
            created_by="admin-uuid",
            days_valid=14,
        )

        assert result is not None
        assert result["code"] == "ABC12345"
        assert result["quota"] == 20

        # Verify RPC was called with correct params
        mock_client.rpc.assert_called_once()
        call_args = mock_client.rpc.call_args
        assert call_args[0][0] == "create_invite_code"

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_returns_none_on_rpc_failure(self, mock_get_client):
        """create_invite_code returns None when RPC fails."""
        from app.infra.supabase_client import create_invite_code

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value.data = None

        result = create_invite_code(email="test@example.com")

        assert result is None

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_returns_none_on_exception(self, mock_get_client):
        """create_invite_code returns None on exception."""
        from app.infra.supabase_client import create_invite_code

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.side_effect = Exception("Connection error")

        result = create_invite_code(email="test@example.com")

        assert result is None


class TestCheckInviteCode:
    """Tests for check_invite_code helper."""

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_returns_valid_true_for_valid_code(self, mock_get_client):
        """check_invite_code returns valid=True for valid code."""
        from app.infra.supabase_client import check_invite_code

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value.data = [
            {"valid": True, "quota": 20, "rsi_quota": 100}
        ]

        result = check_invite_code("VALIDCODE")

        assert result is not None
        assert result["valid"] is True
        assert result["quota"] == 20
        assert result["rsi_quota"] == 100

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_returns_valid_false_for_invalid_code(self, mock_get_client):
        """check_invite_code returns valid=False for invalid/expired code."""
        from app.infra.supabase_client import check_invite_code

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value.data = [
            {"valid": False, "quota": 5, "rsi_quota": 50}
        ]

        result = check_invite_code("EXPIREDCODE")

        assert result is not None
        assert result["valid"] is False

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_returns_none_on_exception(self, mock_get_client):
        """check_invite_code returns None on exception."""
        from app.infra.supabase_client import check_invite_code

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.side_effect = Exception("DB error")

        result = check_invite_code("ANYCODE")

        assert result is None


class TestRevokeInvite:
    """Tests for revoke_invite helper."""

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_returns_true_on_success(self, mock_get_client):
        """revoke_invite returns True when successful."""
        from app.infra.supabase_client import revoke_invite

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value = None

        result = revoke_invite("invite-uuid")

        assert result is True
        mock_client.rpc.assert_called_once_with(
            "revoke_invite", {"p_invite_id": "invite-uuid"}
        )

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_returns_false_on_exception(self, mock_get_client):
        """revoke_invite returns False on exception."""
        from app.infra.supabase_client import revoke_invite

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.side_effect = Exception("RPC error")

        result = revoke_invite("invite-uuid")

        assert result is False


class TestGetUserById:
    """Tests for get_user_by_id helper."""

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_returns_profile_on_success(self, mock_get_client):
        """get_user_by_id returns profile dict when found."""
        from app.infra.supabase_client import get_user_by_id

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": "user-uuid",
            "email": "user@example.com",
            "role": "user",
            "status": "active",
            "daily_quota": 5,
        }

        result = get_user_by_id("user-uuid")

        assert result is not None
        assert result["email"] == "user@example.com"
        assert result["daily_quota"] == 5

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_returns_none_when_not_found(self, mock_get_client):
        """get_user_by_id returns None when user doesn't exist."""
        from app.infra.supabase_client import get_user_by_id

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = None

        result = get_user_by_id("nonexistent-uuid")

        assert result is None

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_returns_none_on_exception(self, mock_get_client):
        """get_user_by_id returns None on exception."""
        from app.infra.supabase_client import get_user_by_id

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.side_effect = Exception("DB error")

        result = get_user_by_id("user-uuid")

        assert result is None


class TestUpdateUserProfile:
    """Tests for update_user_profile helper."""

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_updates_daily_quota(self, mock_get_client):
        """update_user_profile can update daily_quota."""
        from app.infra.supabase_client import update_user_profile

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = None

        result = update_user_profile("user-uuid", daily_quota=20)

        assert result is True
        mock_client.table.return_value.update.return_value.eq.return_value.execute.assert_called_once()

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_updates_multiple_fields(self, mock_get_client):
        """update_user_profile can update multiple fields at once."""
        from app.infra.supabase_client import update_user_profile

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = None

        result = update_user_profile(
            "user-uuid",
            daily_quota=50,
            rsi_daily_quota=200,
            status="suspended",
            role="admin",
        )

        assert result is True

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_returns_false_when_no_fields(self, mock_get_client):
        """update_user_profile returns False when no fields provided."""
        from app.infra.supabase_client import update_user_profile

        result = update_user_profile("user-uuid")

        assert result is False

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_returns_false_on_exception(self, mock_get_client):
        """update_user_profile returns False on exception."""
        from app.infra.supabase_client import update_user_profile

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.side_effect = Exception("DB error")

        result = update_user_profile("user-uuid", daily_quota=10)

        assert result is False
