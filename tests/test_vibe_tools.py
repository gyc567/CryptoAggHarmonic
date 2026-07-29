"""Tests for vibe agent tools."""

from unittest.mock import MagicMock

import pytest

from app.domain.schemas import AnalysisData, AnalysisType, Interval, Market, Status, TechnicalResult
from app.services.vibe.tools import create_default_registry
from app.services.vibe.tools.analyze_harmonic import AnalyzeHarmonicTool
from app.services.vibe.tools.base import ToolRuntime


@pytest.fixture
def registry():
    orchestrator = MagicMock()
    return create_default_registry(orchestrator)


def test_registry_lists_all_tools(registry):
    names = [t.name for t in registry.list_tools()]
    assert "analyze_harmonic" in names
    assert "build_trade_signal" in names
    assert "position_check" in names
    assert "explain_market" in names
    assert "save_to_journal" in names
    assert "backtest_signal" in names


def test_analyze_harmonic_success(registry):
    tool = registry.get("analyze_harmonic")
    assert tool is not None

    # Mock orchestrator result.
    mock_orchestrator = MagicMock()
    mock_orchestrator.analyze.return_value = AnalysisData(
        analysis_id="test-id",
        status=Status.COMPLETED,
        market=Market.BINANCE,
        symbol="BTCUSDT",
        interval=Interval.H1,
        analysis_type=AnalysisType.FORMING,
        technical_result=TechnicalResult(
            direction="bullish",
            pattern_family="xabcd",
            pattern_type="gartley",
            entry_price=67500.0,
            stop_loss=66800.0,
            target_price=69000.0,
            risk_reward_ratio=2.14,
        ),
    )
    tool_instance = AnalyzeHarmonicTool(mock_orchestrator)
    runtime = ToolRuntime(user_id="u1", session_id="s1", run_id="r1")

    output = tool_instance.run(
        {"market": "binance", "symbol": "BTCUSDT", "interval": "1h"},
        runtime,
    )

    assert output.status == "completed"
    assert output.data["symbol"] == "BTCUSDT"
    assert output.data["direction"] == "bullish"
    assert output.data["risk_reward_ratio"] == 2.14


def test_analyze_harmonic_invalid_input(registry):
    tool = registry.get("analyze_harmonic")
    runtime = ToolRuntime(user_id="u1", session_id="s1", run_id="r1")
    output = tool.run({"market": "binance"}, runtime)
    assert output.status == "invalid_input"


def test_backtest_signal_with_mocked_data(monkeypatch):
    orchestrator = MagicMock()
    registry = create_default_registry(orchestrator)
    tool = registry.get("backtest_signal")
    runtime = ToolRuntime(user_id="u1", session_id="s1", run_id="r1")

    import pandas as pd

    df = pd.DataFrame(
        [
            {"dts": "2026-01-01 00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"dts": "2026-01-01 01:00", "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0},
            {"dts": "2026-01-01 02:00", "open": 104.0, "high": 105.0, "low": 100.0, "close": 102.0},
            {"dts": "2026-01-01 03:00", "open": 102.0, "high": 103.0, "low": 98.0, "close": 99.0},
        ]
    )
    df["dts"] = pd.to_datetime(df["dts"])
    df = df.set_index("dts")

    def mock_fetch(*args, **kwargs):
        return df

    from app.services.vibe.tools import backtest_signal as backtest_signal_module

    monkeypatch.setattr(backtest_signal_module, "fetch_historical_data", mock_fetch)

    output = tool.run(
        {
            "market": "binance",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "direction": "long",
            "entry_price": 100,
            "stop_loss": 98,
            "target_price": 105,
            "lookback_days": 30,
        },
        runtime,
    )

    assert output.status == "completed"
    data = output.data
    assert data["status"] == "completed"
    assert data["symbol"] == "BTCUSDT"
    assert data["total_signals"] == 3
    assert data["win_count"] == 2
    assert data["loss_count"] == 1
    assert "avg_rr" in data
