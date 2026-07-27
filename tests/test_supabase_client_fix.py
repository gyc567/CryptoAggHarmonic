"""Fixed tests for Supabase client module."""
import pytest
from unittest.mock import MagicMock, patch

from app.infra.supabase_client import (
    get_supabase_url,
    get_supabase_anon_key,
    get_supabase_service_key,
    get_db_connection_string,
    verify_user_token,
    check_invited_email,
    create_profile_for_user,
    get_user_profile,
    list_user_analyses,
    create_analysis_record,
    update_analysis_record,
    reserve_user_quota,
    consume_ledger_quota,
    release_ledger_quota,
    upload_chart,
    get_chart_url,
    delete_chart,
    log_audit_event,
)
from app.api.errors import AppError


class TestVerifyUserToken:
    def test_valid_token(self):
        mock_user = MagicMock()
        mock_user.user.id = "user-123"
        mock_user.user.email = "test@example.com"

        mock_anon_client = MagicMock()
        mock_anon_client.auth.get_user.return_value = mock_user

        mock_service_client = MagicMock()
        mock_profile_result = MagicMock()
        mock_profile_result.data = {
            "role": "user",
            "status": "active",
            "daily_quota": 5,
        }
        mock_service_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_profile_result

        def get_client_side_effect(use_service_role=False):
            return mock_service_client if use_service_role else mock_anon_client

        with patch("app.infra.supabase_client.get_supabase_client", side_effect=get_client_side_effect):
            result = verify_user_token("valid-token")

        assert result is not None
        assert result["id"] == "user-123"
        assert result["email"] == "test@example.com"
        assert result["role"] == "user"
        assert result["daily_quota"] == 5

    def test_invalid_token(self):
        mock_anon_client = MagicMock()
        mock_anon_client.auth.get_user.side_effect = Exception("Invalid token")

        def get_client_side_effect(use_service_role=False):
            return mock_anon_client

        with patch("app.infra.supabase_client.get_supabase_client", side_effect=get_client_side_effect):
            result = verify_user_token("invalid-token")

        assert result is None
