"""API tests for GET /api/rsi-trend/plan."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from flask import Flask

from app.api.middleware import register_error_handlers
from app.api.rsi_trend_routes import rsi_trend_bp


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    register_error_handlers(app)
    app.register_blueprint(rsi_trend_bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def local_dev(monkeypatch):
    """Disable auth + quota for testing."""
    monkeypatch.setenv("DISABLE_AUTH", "1")


class TestPlan:
    def test_plan_success(self, client):
        """Plan endpoint returns a full TradingPlan on success."""
        mock_plan = {
            "symbol": "BTCUSDT",
            "interval": "4h",
            "generated_at": "2026-01-01T00:00:00Z",
            "plan_non_prod": True,
            "market_overview": {"trend": "bullish", "trend_strength": 0.7},
            "decision": {"action": "trade", "direction": "long", "confidence": 0.75,
                         "reasons": [], "warnings": []},
            "plan": None,
            "multi_tf": None,
            "invalidation": [],
            "history": {},
            "ai_insight": None,
        }
        with patch("app.api.rsi_trend_routes.build_plan", return_value=mock_plan):
            resp = client.get(
                "/api/rsi-trend/plan?market=binance&symbol=BTCUSDT&interval=4h",
                
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        inner = data["data"]
        assert inner["symbol"] == "BTCUSDT"
        assert inner["decision"]["action"] == "trade"

    def test_plan_missing_symbol(self, client):
        """400 when symbol is missing."""
        resp = client.get(
            "/api/rsi-trend/plan?market=binance&interval=4h",
            
        )
        assert resp.status_code == 422

    def test_plan_quota_exceeded(self, client):
        """429 when quota exceeded."""
        # Override autouse fixture
        with patch("app.api.rsi_trend_routes._reserve_quota", return_value=False):
            resp = client.get(
                "/api/rsi-trend/plan?market=binance&symbol=BTCUSDT&interval=4h",
                
            )
        assert resp.status_code == 429

    def test_plan_internal_error_releases_quota(self, client):
        """On error, ledger is released."""
        mock_ledger = "ledger-123"
        with (
            patch("app.api.rsi_trend_routes._reserve_quota", return_value=mock_ledger),
            patch("app.api.rsi_trend_routes.build_plan", side_effect=RuntimeError("boom")),
            patch("app.api.rsi_trend_routes.release_ledger_quota") as mock_release,
        ):
            resp = client.get(
                "/api/rsi-trend/plan?market=binance&symbol=BTCUSDT&interval=4h",
                
            )
        assert resp.status_code == 500
        mock_release.assert_called_once_with(mock_ledger)

