"""Tests for Supabase client module."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

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
    get_analysis_by_idem_key,
    reset_idem_cache,
)
from app.api.errors import AppError


class TestEnvironmentFunctions:
    @patch.dict("os.environ", {"SUPABASE_URL": "https://test.supabase.co"}, clear=False)
    def test_get_supabase_url(self):
        assert get_supabase_url() == "https://test.supabase.co"

    @patch.dict("os.environ", {}, clear=True)
    def test_get_supabase_url_missing(self):
        with pytest.raises(RuntimeError):
            get_supabase_url()

    @patch.dict("os.environ", {"SUPABASE_URL": "", "SUPABASE_DB_URL": "postgresql://user:pass@db.test.supabase.co:5432/postgres"}, clear=True)
    def test_get_supabase_url_from_db_url(self):
        url = get_supabase_url()
        assert "test.supabase.co" in url

    @patch.dict("os.environ", {"SUPABASE_ANON_KEY": "test-anon-key"}, clear=True)
    def test_get_supabase_anon_key(self):
        assert get_supabase_anon_key() == "test-anon-key"

    @patch.dict("os.environ", {"SUPABASE_ANON_KEY": "sb_publishable_OUSZKe4KXufvYWkTNrcSHg_xvMk44Or"}, clear=True)
    def test_get_supabase_publishable_key_format(self):
        """New Publishable Key format (sb_publishable_...) is accepted as anon key."""
        key = get_supabase_anon_key()
        assert key.startswith("sb_publishable_")
        assert "OUSZKe4KXufvYWkTNrcSHg" in key

    @patch.dict("os.environ", {}, clear=True)
    def test_get_supabase_anon_key_missing(self):
        with pytest.raises(RuntimeError):
            get_supabase_anon_key()

    @patch.dict("os.environ", {"SUPABASE_SERVICE_ROLE_KEY": "test-service-key"}, clear=True)
    def test_get_supabase_service_key(self):
        assert get_supabase_service_key() == "test-service-key"

    @patch.dict("os.environ", {"SUPABASE_SECRET_KEY": "sb_secret_a_test123"}, clear=True)
    def test_get_supabase_secret_key_fallback(self):
        """New Secret Key format (sb_secret_a_...) works as fallback."""
        assert get_supabase_service_key() == "sb_secret_a_test123"

    @patch.dict("os.environ", {}, clear=True)
    def test_get_supabase_service_key_missing(self):
        with pytest.raises(RuntimeError):
            get_supabase_service_key()

    @patch.dict("os.environ", {"SUPABASE_DB_URL": "postgresql://user:pass@host:5432/db"}, clear=True)
    def test_get_db_connection_string(self):
        conn_str = get_db_connection_string()
        assert "postgresql://" in conn_str
        assert "host" in conn_str

    @patch.dict("os.environ", {
        "SUPABASE_DB_HOST": "db.test.supabase.co",
        "SUPABASE_DB_PORT": "5432",
        "SUPABASE_DB_USER": "postgres",
        "SUPABASE_DB_PASSWORD": "test!pass@123",
        "SUPABASE_DB_NAME": "postgres",
    }, clear=True)
    def test_get_db_connection_string_from_components(self):
        conn_str = get_db_connection_string()
        assert "db.test.supabase.co" in conn_str
        assert "test%21pass%40123" in conn_str  # URL encoded


class TestVerifyUserToken:
    def _client_factory(self, anon_client, service_client):
        def factory(use_service_role=False):
            return service_client if use_service_role else anon_client
        return factory

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_valid_token(self, mock_get_client):
        mock_user = MagicMock()
        mock_user.user.id = "user-123"
        mock_user.user.email = "test@example.com"

        mock_anon_client = MagicMock()
        mock_anon_client.auth.get_user.return_value = mock_user

        mock_service_client = MagicMock()
        mock_profile_data = {
            "role": "user",
            "status": "active",
            "daily_quota": 5,
        }
        mock_profile_result = MagicMock()
        mock_profile_result.data = mock_profile_data
        mock_service_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_profile_result

        mock_get_client.side_effect = self._client_factory(mock_anon_client, mock_service_client)
        result = verify_user_token("valid-token")

        assert result is not None
        assert result["id"] == "user-123"
        assert result["email"] == "test@example.com"
        assert result["role"] == "user"
        assert result["daily_quota"] == 5

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_invalid_token(self, mock_get_client):
        mock_anon_client = MagicMock()
        mock_anon_client.auth.get_user.side_effect = Exception("Invalid token")

        mock_get_client.side_effect = self._client_factory(mock_anon_client, MagicMock())
        result = verify_user_token("invalid-token")

        assert result is None


class TestCheckInvitedEmail:
    @patch("app.infra.supabase_client.get_supabase_client")
    def test_invited_email(self, mock_get_client):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.data = True
        mock_client.rpc.return_value.execute.return_value = mock_result
        mock_get_client.return_value = mock_client

        result = check_invited_email("test@example.com")
        assert result is True

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_not_invited(self, mock_get_client):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.data = False
        mock_client.rpc.return_value.execute.return_value = mock_result
        mock_get_client.return_value = mock_client

        result = check_invited_email("unknown@example.com")
        assert result is False


class TestProfileFunctions:
    @patch("app.infra.supabase_client.get_supabase_client")
    def test_create_profile(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = create_profile_for_user("user-123", "test@example.com", 10)
        assert result is True
        mock_client.table.return_value.insert.assert_called_once()

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_create_profile_failure(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.table.return_value.insert.side_effect = Exception("DB error")
        mock_get_client.return_value = mock_client

        result = create_profile_for_user("user-123", "test@example.com")
        assert result is False

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_get_user_profile(self, mock_get_client):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.data = {"id": "user-123", "role": "admin"}
        mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_result
        mock_get_client.return_value = mock_client

        result = get_user_profile("user-123")
        assert result is not None
        assert result["role"] == "admin"

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_get_user_profile_not_found(self, mock_get_client):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.data = None
        mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_result
        mock_get_client.return_value = mock_client

        result = get_user_profile("user-999")
        assert result is None


class TestAnalysisFunctions:
    @patch("app.infra.supabase_client.get_supabase_client")
    def test_list_user_analyses(self, mock_get_client):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"id": "a1", "symbol": "BTCUSDT", "status": "completed"},
            {"id": "a2", "symbol": "AAPL", "status": "no_result"},
        ]
        mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.offset.return_value.execute.return_value = mock_result
        mock_get_client.return_value = mock_client

        result = list_user_analyses("user-123", limit=10)
        assert len(result) == 2
        assert result[0]["symbol"] == "BTCUSDT"

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_list_user_analyses_with_filters(self, mock_get_client):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [{"id": "a1", "symbol": "BTCUSDT", "status": "completed", "market": "binance"}]
        mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.offset.return_value.eq.return_value.eq.return_value.execute.return_value = mock_result
        mock_get_client.return_value = mock_client

        result = list_user_analyses("user-123", status="completed", market="binance")
        assert len(result) == 1

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_create_analysis_record(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = create_analysis_record("user-123", {"symbol": "BTCUSDT", "market": "binance"})
        assert result is not None
        assert len(result) == 36  # UUID length

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_update_analysis_record(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = update_analysis_record("analysis-123", {"status": "completed"})
        assert result is True

    def test_get_analysis_by_idem_key_skips_on_empty_args(self):
        """Empty user_id / idem_key short-circuits to None without hitting Supabase."""
        reset_idem_cache()
        assert get_analysis_by_idem_key("", "key") is None
        assert get_analysis_by_idem_key("user", "") is None

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_get_analysis_by_idem_key_miss_then_hit(self, mock_get_client):
        """First call hits Supabase and caches the result; second call reuses cache."""
        reset_idem_cache()
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [{"id": "a1", "user_id": "user-1", "idempotency_key": "k1", "status": "completed", "technical_result": {"x": 1}}]
        (
            mock_client.table.return_value
            .select.return_value
            .eq.return_value
            .eq.return_value
            .order.return_value
            .limit.return_value
            .execute.return_value
        ) = mock_result
        mock_get_client.return_value = mock_client

        first = get_analysis_by_idem_key("user-1", "k1")
        assert first["id"] == "a1"

        # Second call should not call Supabase again (cache hit).
        second = get_analysis_by_idem_key("user-1", "k1")
        assert second == first
        # Same row dict reused, no extra .execute() invocations.
        assert mock_client.table.call_count == 1

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_get_analysis_by_idem_key_handles_errors(self, mock_get_client):
        """Supabase errors degrade to None (treated as miss) and are cached as such."""
        reset_idem_cache()
        mock_get_client.side_effect = RuntimeError("supabase down")
        assert get_analysis_by_idem_key("user-1", "k-err") is None


class TestQuotaFunctions:
    @patch("app.infra.supabase_client.get_supabase_client")
    def test_reserve_user_quota(self, mock_get_client):
        mock_client = MagicMock()

        mock_reserve_result = MagicMock()
        mock_reserve_result.data = [{"reserved": True, "remaining": 4}]
        mock_client.rpc.return_value.execute.return_value = mock_reserve_result

        mock_ledger_result = MagicMock()
        mock_ledger_result.data = [{"id": "ledger-123"}]
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_ledger_result

        mock_get_client.return_value = mock_client

        success, remaining, ledger_id = reserve_user_quota("user-123", "analysis-123", 1)
        assert success is True
        assert remaining == 4
        assert ledger_id == "ledger-123"

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_reserve_user_quota_insufficient(self, mock_get_client):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [{"reserved": False, "remaining": 0}]
        mock_client.rpc.return_value.execute.return_value = mock_result
        mock_get_client.return_value = mock_client

        success, remaining, ledger_id = reserve_user_quota("user-123", "analysis-123", 1)
        assert success is False
        assert remaining == 0

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_consume_ledger_quota(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = consume_ledger_quota("ledger-123", 100, 50, 5000)
        assert result is True

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_release_ledger_quota(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = release_ledger_quota("ledger-123")
        assert result is True


class TestStorageFunctions:
    @patch("app.infra.supabase_client.get_supabase_client")
    def test_upload_chart(self, mock_get_client):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.data = {"path": "user-123/analysis-123.png"}
        mock_client.storage.from_.return_value.upload.return_value = mock_result
        mock_get_client.return_value = mock_client

        result = upload_chart("user-123", "analysis-123", b"fake_image")
        assert result is not None
        assert "user-123/analysis-123.png" in result

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_get_chart_url(self, mock_get_client):
        mock_client = MagicMock()
        mock_result = {"signedURL": "https://signed.url/chart.png"}
        mock_client.storage.from_.return_value.create_signed_url.return_value = mock_result
        mock_get_client.return_value = mock_client

        result = get_chart_url("user-123/analysis-123.png")
        assert result == "https://signed.url/chart.png"

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_delete_chart(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = delete_chart("user-123/analysis-123.png")
        assert result is True


class TestAuditFunctions:
    @patch("app.infra.supabase_client.get_supabase_client")
    def test_log_audit_event(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = log_audit_event("user-123", "invite_user", "user", "user-456", {"email": "test@example.com"})
        assert result is True

    @patch("app.infra.supabase_client.get_supabase_client")
    def test_log_audit_event_failure(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.table.return_value.insert.side_effect = Exception("DB error")
        mock_get_client.return_value = mock_client

        result = log_audit_event("user-123", "action", "type")
        assert result is False
