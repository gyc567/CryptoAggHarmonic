"""Integration tests for new API endpoints."""
import os
import pytest
from unittest.mock import MagicMock, patch
import app.main as main_module
from app.main import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        with patch.dict(os.environ, {"DISABLE_AUTH": "1"}, clear=False):
            yield client


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token-123"}


@pytest.fixture(autouse=True)
def mock_auth():
    """Auto-use mock authentication for all tests in this module."""
    mock_user = {
        "id": "test-user-123",
        "email": "test@example.com",
        "role": "user",
        "status": "active",
        "daily_quota": 5,
    }
    
    # Mock orchestrator.analyze to accept any args/kwargs and return a valid response
    def mock_analyze(*args, user_id=None, analysis_id=None, **kwargs):
        from app.domain.enums import Status, Market, Interval, AnalysisType
        from app.domain.schemas import AnalysisData, TechnicalResult, ChartMeta, TimingInfo
        return AnalysisData(
            analysis_id=analysis_id or "test-id",
            status=Status.COMPLETED,
            market=Market.BINANCE,
            symbol="BTCUSDT",
            interval=Interval.D1,
            analysis_type=AnalysisType.FORMING,
            technical_result=TechnicalResult(),
            chart=ChartMeta(),
            timing=TimingInfo(duration_ms=1000, started_at="1234567890", completed_at="1234567891"),
        )
    
    with patch("app.api.auth.verify_user_token", return_value=mock_user), \
         patch("app.api.auth.check_quota", return_value=(True, 4, "ledger-123")), \
         patch("app.api.auth.reserve_user_quota", return_value=(True, 4, "ledger-123")), \
         patch("app.api.auth.release_ledger_quota", return_value=True), \
         patch("app.main.release_ledger_quota", return_value=True), \
         patch("app.main.consume_ledger_quota", return_value=True), \
         patch("app.main.create_analysis_record", return_value=("analysis-123", None)), \
         patch("app.main.get_analysis_by_idem_key", return_value=None), \
         patch("app.infra.supabase_client.consume_ledger_quota", return_value=True), \
         patch("app.infra.supabase_client.release_ledger_quota", return_value=True), \
         patch("app.infra.supabase_client.create_analysis_record", return_value=("analysis-123", None)), \
         patch("app.infra.supabase_client.get_analysis_by_idem_key", return_value=None), \
         patch("app.infra.supabase_client.log_audit_event", return_value=True):
        # Mock the orchestrator's analyze method directly on the module instance
        main_module.orchestrator.analyze = mock_analyze
        yield mock_user


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["version"] == "0.2.0"
        assert "timestamp" in data


class TestMarketsEndpoint:
    def test_markets_returns_all(self, client):
        resp = client.get("/api/markets")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "markets" in data
        assert "intervals" in data
        assert "analysis_types" in data
        assert "binance" in data["markets"]
        assert "yahoo" in data["markets"]
        assert "1d" in data["intervals"]
        assert "forming" in data["analysis_types"]


class TestAnalyzeEndpoint:
    def test_analyze_missing_body(self, client, auth_headers):
        resp = client.post("/api/analyze", headers=auth_headers)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAMS"

    def test_analyze_empty_json(self, client, auth_headers):
        resp = client.post("/api/analyze", json={}, headers=auth_headers)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAMS"

    def test_analyze_invalid_symbol(self, client, auth_headers):
        resp = client.post("/api/analyze", json={
            "market": "binance",
            "symbol": "",
            "interval": "1d",
        }, headers=auth_headers)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

    def test_analyze_invalid_market(self, client, auth_headers):
        resp = client.post("/api/analyze", json={
            "market": "kraken",
            "symbol": "BTCUSDT",
            "interval": "1d",
        }, headers=auth_headers)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

    def test_analyze_invalid_interval(self, client, auth_headers):
        resp = client.post("/api/analyze", json={
            "market": "binance",
            "symbol": "BTCUSDT",
            "interval": "99h",  # Not a valid interval
        }, headers=auth_headers)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

    def test_analyze_success(self, client, auth_headers):
        resp = client.post("/api/analyze", json={
            "market": "binance",
            "symbol": "BTCUSDT",
            "interval": "1d",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["data"]["status"] == "completed"
        assert data["data"]["symbol"] == "BTCUSDT"

    def test_analyze_with_params(self, client, auth_headers):
        resp = client.post("/api/analyze", json={
            "market": "binance",
            "symbol": "BTCUSDT",
            "interval": "1d",
            "analysis_type": "forming",
            "limit_to": 10,
            "percent_complete": 0.8,
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["data"]["status"] == "completed"

    def test_analyze_yahoo_market(self, client, auth_headers):
        resp = client.post("/api/analyze", json={
            "market": "yahoo",
            "symbol": "AAPL",
            "interval": "1d",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["market"] == "binance"  # Mock returns BINANCE

    def test_analyze_idempotency_key(self, client, auth_headers):
        resp = client.post("/api/analyze", json={
            "market": "binance",
            "symbol": "BTCUSDT",
            "interval": "1d",
            "idempotency_key": "my-key-123",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_analyze_formed_analysis_type(self, client, auth_headers):
        resp = client.post("/api/analyze", json={
            "market": "binance",
            "symbol": "BTCUSDT",
            "interval": "1w",
            "analysis_type": "formed",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["analysis_type"] == "forming"  # Mock returns FORMING

    def test_analyze_divergence_type(self, client, auth_headers):
        resp = client.post("/api/analyze", json={
            "market": "yahoo",
            "symbol": "TSLA",
            "interval": "1h",
            "analysis_type": "divergence",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["analysis_type"] == "forming"  # Mock returns FORMING

    def test_analyze_market_data_error(self, client, auth_headers):
        """Test that AppError with MARKET_DATA_UNAVAILABLE returns 503."""
        from app.api.errors import AppError
        from app.domain.enums import ErrorCode
        
        def error_analyze(*args, user_id=None, analysis_id=None, **kwargs):
            raise AppError(
                ErrorCode.MARKET_DATA_UNAVAILABLE,
                "暂时无法获取行情",
                retryable=True,
            )
        
        original_analyze = main_module.orchestrator.analyze
        main_module.orchestrator.analyze = error_analyze
        
        try:
            resp = client.post("/api/analyze", json={
                "market": "binance",
                "symbol": "BTCUSDT",
                "interval": "1d",
            }, headers=auth_headers)
            assert resp.status_code == 503
            data = resp.get_json()
            assert data["success"] is False
            assert data["error"]["code"] == "MARKET_DATA_UNAVAILABLE"
            assert data["error"]["retryable"] is True
        finally:
            main_module.orchestrator.analyze = original_analyze

    def test_analyze_internal_error(self, client, auth_headers):
        """Test that unexpected errors return 500."""
        def error_analyze(*args, user_id=None, analysis_id=None, **kwargs):
            raise RuntimeError("Unexpected")
        
        original_analyze = main_module.orchestrator.analyze
        main_module.orchestrator.analyze = error_analyze
        
        try:
            resp = client.post("/api/analyze", json={
                "market": "binance",
                "symbol": "BTCUSDT",
                "interval": "1d",
            }, headers=auth_headers)
            assert resp.status_code == 500
            data = resp.get_json()
            assert data["success"] is False
            assert data["error"]["code"] == "INTERNAL_ERROR"
            assert "request_id" in data["error"]
        finally:
            main_module.orchestrator.analyze = original_analyze
