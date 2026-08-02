"""Integration tests for app.services.rsi_trend_plan_service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.domain.rsi_trend_schemas import RsiTrendScanRequest
from app.services.rsi_trend_plan_service import _AI_CACHE


@pytest.fixture(autouse=True)
def clear_ai_cache():
    """Prevent cache leakage between tests."""
    _AI_CACHE.clear()
    yield
    _AI_CACHE.clear()


@pytest.fixture
def req():
    return RsiTrendScanRequest(
        market="binance", symbol="BTCUSDT", interval="4h",
        use_ema50=False, require_candle_color=False,
        atr_mult=1.0, rsi_zone="pullback", reward_risk=2.0, min_quality_score=30,
    )


@pytest.fixture
def mock_scan():
    """Return an _ScanCore-like tuple (df, state, signals)."""
    from app.domain.rsi_trend import LONG, StrategySignal

    df = pd.DataFrame({
        "open": [100.0] * 300,
        "high": [101.0] * 300,
        "low": [99.0] * 300,
        "close": [100.0] * 300,
    })
    state = {
        "time": "2026-01-01",
        "close": 100.0,
        "ema200": 90.0,
        "ema50": 95.0,
        "rsi": 55.0,
        "atr": 1.5,
        "trend": "bullish",
        "deviation_pct": 10.0,
        "entangled": False,
    }
    signal = StrategySignal(
        direction=LONG, entry_price=100.0, stop_loss=95.0,
        target_price=110.0, atr=1.5, rsi=45.0,
        time="2026-01-01", index=298, quality_score=78,
    )
    return df, state, [signal]


def test_build_plan_trade(mock_scan, req):
    """Full plan for a trade signal — mocked position + LLM."""
    from app.services.rsi_trend_plan_service import build_plan

    df, state, signals = mock_scan
    with (
        patch("app.services.rsi_trend_plan_service._scan_core") as mock_core,
        patch("app.services.rsi_trend_plan_service.get_position_config") as mock_pos,
        patch("app.services.rsi_trend_plan_service.llm_complete") as mock_llm,
    ):
        from app.services.rsi_trend_service import _ScanCore
        mock_core.return_value = _ScanCore(df=df, state=state, signals=signals)
        mock_pos.return_value = None  # no position config
        mock_llm.return_value = '{"summary":"多头趋势良好","risk_note":"控制仓位"}'

        result = build_plan(req, user_id="test-user")

    assert result["symbol"] == "BTCUSDT"
    assert result["decision"]["action"] == "trade"
    assert result["decision"]["direction"] == "long"
    assert result["plan"] is not None
    assert len(result["plan"]["targets"]) == 3
    assert result["plan"]["position"]["configured"] is False
    assert result["ai_insight"] is not None
    assert "多头趋势良好" in result["ai_insight"]["summary"]


def test_build_plan_no_signal(req):
    """No signals → no_trade."""
    from app.services.rsi_trend_plan_service import build_plan

    df = pd.DataFrame({"open": [100]*300, "high": [101]*300, "low": [99]*300, "close": [100]*300})
    state = {"time": "2026-01-01", "close": 100.0, "ema200": 90.0, "ema50": 95.0,
             "rsi": 60.0, "atr": 1.0, "trend": "bullish", "deviation_pct": 10.0, "entangled": False}

    with patch("app.services.rsi_trend_plan_service._scan_core") as mock_core:
        from app.services.rsi_trend_service import _ScanCore
        mock_core.return_value = _ScanCore(df=df, state=state, signals=[])
        result = build_plan(req, user_id="test-user")

    assert result["decision"]["action"] == "no_trade"
    assert result["plan"] is None


def test_build_plan_with_position(req, mock_scan):
    """Position config exists → position computed."""
    from app.services.rsi_trend_plan_service import build_plan

    df, state, signals = mock_scan
    pos_cfg = {"totalCapitalWu": 100_000, "emergencyRatio": 0.3, "btcRatio": 0.4,
               "altcoinMaxRatio": 0.15, "midAccountRatio": 0.2, "smallAccountRatio": 0.05,
               "smallTradableRatio": 0.6}

    with (
        patch("app.services.rsi_trend_plan_service._scan_core") as mock_core,
        patch("app.services.rsi_trend_plan_service.get_position_config") as mock_pos,
        patch("app.services.rsi_trend_plan_service.llm_complete") as mock_llm,
    ):
        from app.services.rsi_trend_service import _ScanCore
        mock_core.return_value = _ScanCore(df=df, state=state, signals=signals)
        mock_pos.return_value = {"position_config": pos_cfg, "position_balance": None}
        mock_llm.return_value = '{"summary":"ok","risk_note":"ok"}'

        result = build_plan(req, user_id="test-user")

    assert result["plan"]["position"]["configured"] is True
    assert result["plan"]["position"]["position_size_u"] > 0


def test_build_plan_llm_failure_graceful(req, mock_scan):
    """LLM fails → ai_insight is None, plan still complete."""
    from app.services.rsi_trend_plan_service import build_plan

    df, state, signals = mock_scan
    with (
        patch("app.services.rsi_trend_plan_service._scan_core") as mock_core,
        patch("app.services.rsi_trend_plan_service.get_position_config") as mock_pos,
        patch("app.services.rsi_trend_plan_service.llm_complete") as mock_llm,
    ):
        from app.services.rsi_trend_service import _ScanCore
        mock_core.return_value = _ScanCore(df=df, state=state, signals=signals)
        mock_pos.return_value = None
        mock_llm.return_value = None  # LLM failed

        result = build_plan(req, user_id="test-user")

    assert result["plan"] is not None           # rule engine still works
    assert result["ai_insight"] is None          # LLM gracefully absent


def test_derive_appetite():
    from app.services.rsi_trend_plan_service import _derive_appetite
    assert _derive_appetite({"emergencyRatio": 0.4, "altcoinMaxRatio": 0.1}) == "conservative"
    assert _derive_appetite({"emergencyRatio": 0.3, "altcoinMaxRatio": 0.25}) == "aggressive"
    assert _derive_appetite({"emergencyRatio": 0.3, "altcoinMaxRatio": 0.1}) == "balanced"


def test_time_stop():
    from app.services.rsi_trend_plan_service import _time_stop
    assert "48" in _time_stop("4h")
    assert "20" in _time_stop("1d")
    assert "8" in _time_stop("1w")


def test_invalidation_messages():
    from app.services.rsi_trend_plan_service import _invalidation_trend, _invalidation_stop, _invalidation_signal
    assert "跌破 EMA200" in _invalidation_trend("long", 64000)
    assert "突破 EMA200" in _invalidation_trend("short", 64000)
    assert "止损" in _invalidation_stop("long", 100)
    assert "RSI 重新跌破 30" in _invalidation_signal("long")
