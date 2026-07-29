"""API tests for the trend-RSI strategy blueprint (/api/rsi-trend/*)."""
from __future__ import annotations

import pandas as pd
import pytest
from flask import Flask
from unittest.mock import MagicMock, patch

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
    monkeypatch.setenv("DISABLE_AUTH", "1")


@pytest.fixture(autouse=True)
def no_audit():
    with patch("app.api.rsi_trend_routes.log_audit_event", return_value=True):
        yield


def make_df(closes: list[float]) -> pd.DataFrame:
    opens = [closes[0]] + closes[:-1]
    return pd.DataFrame({
        "open": opens,
        "close": closes,
        "high": [max(o, c) + 0.5 for o, c in zip(opens, closes)],
        "low": [min(o, c) - 0.5 for o, c in zip(opens, closes)],
    })


def uptrend_dip_df() -> pd.DataFrame:
    """200-bar uptrend, sharp dip (RSI<30), bounce crossing back up (1 long signal)."""
    closes = [100.0 + i for i in range(200)] + [284.0, 269.0, 254.0, 262.0]
    return make_df(closes)


def mock_candle_data(df: pd.DataFrame) -> MagicMock:
    mock = MagicMock()
    mock.df = df
    return mock


class TestScan:
    def test_scan_success(self, client):
        with patch(
            "app.services.rsi_trend_service.fetch_market_data",
            return_value=mock_candle_data(uptrend_dip_df()),
        ):
            resp = client.get("/api/rsi-trend/scan?symbol=BTCUSDT&interval=4h")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        data = body["data"]
        assert data["symbol"] == "BTCUSDT"
        assert data["state"]["trend"] == "bullish"
        assert data["latest_signal"]["direction"] == "long"
        assert data["latest_signal"]["stop_loss"] < data["latest_signal"]["entry_price"]
        assert len(data["recent_signals"]) == 1

    def test_scan_missing_symbol(self, client):
        resp = client.get("/api/rsi-trend/scan")
        # Schema-level rejection (missing required field) → 422.
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "INVALID_PARAMS"

    def test_scan_yahoo_rejects_4h(self, client):
        resp = client.get("/api/rsi-trend/scan?market=yahoo&symbol=AAPL&interval=4h")
        # Cross-field validator on RsiTrendScanRequest (yahoo rejects 4h) → 422.
        assert resp.status_code == 422
        assert "1d" in resp.get_json()["error"]["message"]

    def test_scan_insufficient_bars(self, client):
        with patch(
            "app.services.rsi_trend_service.fetch_market_data",
            return_value=mock_candle_data(make_df([100.0] * 100)),
        ):
            resp = client.get("/api/rsi-trend/scan?symbol=BTCUSDT")
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INVALID_PARAMS"

    def test_scan_unauthorized(self, client, monkeypatch):
        monkeypatch.delenv("DISABLE_AUTH", raising=False)
        resp = client.get("/api/rsi-trend/scan?symbol=BTCUSDT")
        assert resp.status_code == 401


class TestBacktest:
    def test_backtest_success(self, client):
        # signal at the last bar flattens at end of data -> 1 scratch trade
        with patch(
            "app.services.rsi_trend_service.fetch_historical_data",
            return_value=uptrend_dip_df(),
        ):
            resp = client.post(
                "/api/rsi-trend/backtest",
                json={"symbol": "BTCUSDT", "interval": "4h", "lookback_days": 180},
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        data = body["data"]
        assert data["total_signals"] == 1
        assert data["trades_count"] == 1
        assert data["trades"][0]["exit_reason"] == "end_of_data"
        assert "win_rate" in data and "profit_factor" in data
        assert data["filters"]["partial_mode"] is False

    def test_backtest_partial_mode_flag(self, client):
        with patch(
            "app.services.rsi_trend_service.fetch_historical_data",
            return_value=uptrend_dip_df(),
        ):
            resp = client.post(
                "/api/rsi-trend/backtest",
                json={"symbol": "ethusdt", "partial_mode": True, "use_ema50": True},
            )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["symbol"] == "ETHUSDT"
        assert data["filters"]["partial_mode"] is True
        # EMA50 filter vetoes the post-dip signal (close below EMA50)
        assert data["total_signals"] == 0

    def test_backtest_invalid_params(self, client):
        resp = client.post("/api/rsi-trend/backtest", json={"symbol": ""})
        # Schema-level rejection (empty symbol after constraint check) → 422.
        assert resp.status_code == 422

    def test_backtest_lookback_out_of_range(self, client):
        resp = client.post(
            "/api/rsi-trend/backtest",
            json={"symbol": "BTCUSDT", "lookback_days": 1000},
        )
        # Schema-level rejection (lookback_days exceeds le=365) → 422.
        assert resp.status_code == 422

    def test_backtest_data_unavailable(self, client):
        with patch(
            "app.services.rsi_trend_service.fetch_historical_data",
            side_effect=RuntimeError("No historical data returned"),
        ):
            resp = client.post("/api/rsi-trend/backtest", json={"symbol": "BTCUSDT"})
        assert resp.status_code == 503
        assert resp.get_json()["error"]["code"] == "MARKET_DATA_UNAVAILABLE"
