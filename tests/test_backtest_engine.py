"""Tests for the vibe backtest engine."""

import pandas as pd
import pytest

from app.services.vibe.backtest_engine import (
    Trade,
    compute_metrics,
    simulate_trades,
)


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """Build a DataFrame from OHLCV rows indexed by timestamp."""
    df = pd.DataFrame(rows)
    df["dts"] = pd.to_datetime(df["dts"])
    df = df.set_index("dts")
    return df


def test_simulate_long_win():
    df = _make_df(
        [
            {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 99, "close": 100},
            {"dts": "2026-01-01 01:00", "open": 100, "high": 105, "low": 99, "close": 104},
        ]
    )
    trades = simulate_trades(df, "long", 100, 98, 105)
    assert len(trades) == 1
    assert trades[0].result == "win"
    assert trades[0].exit_price == 105


def test_simulate_long_stop():
    df = _make_df(
        [
            {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 99, "close": 100},
            {"dts": "2026-01-01 01:00", "open": 100, "high": 102, "low": 97, "close": 98},
        ]
    )
    trades = simulate_trades(df, "long", 100, 98, 105)
    assert len(trades) == 1
    assert trades[0].result == "loss"
    assert trades[0].exit_price == 98


def test_simulate_short_win():
    df = _make_df(
        [
            {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 99, "close": 100},
            {"dts": "2026-01-01 01:00", "open": 100, "high": 101, "low": 95, "close": 96},
        ]
    )
    trades = simulate_trades(df, "short", 100, 103, 95)
    assert len(trades) == 1
    assert trades[0].result == "win"
    assert trades[0].exit_price == 95


def test_simulate_short_stop():
    df = _make_df(
        [
            {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 99, "close": 100},
            {"dts": "2026-01-01 01:00", "open": 100, "high": 104, "low": 99, "close": 102},
        ]
    )
    trades = simulate_trades(df, "short", 100, 103, 95)
    assert len(trades) == 1
    assert trades[0].result == "loss"
    assert trades[0].exit_price == 103


def test_simulate_multiple_entries():
    df = _make_df(
        [
            {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 99, "close": 100},
            {"dts": "2026-01-01 01:00", "open": 100, "high": 105, "low": 99, "close": 104},
            {"dts": "2026-01-01 02:00", "open": 104, "high": 105, "low": 100, "close": 102},
            {"dts": "2026-01-01 03:00", "open": 102, "high": 103, "low": 98, "close": 99},
        ]
    )
    trades = simulate_trades(df, "long", 100, 98, 105)
    assert len(trades) == 3
    assert trades[0].result == "win"
    assert trades[1].result == "win"
    assert trades[2].result == "loss"


def test_simulate_same_candle_exit_long():
    df = _make_df(
        [
            {"dts": "2026-01-01 00:00", "open": 100, "high": 105, "low": 99, "close": 104},
        ]
    )
    trades = simulate_trades(df, "long", 100, 98, 105)
    assert len(trades) == 1
    assert trades[0].result == "win"
    assert trades[0].exit_price == 105


def test_simulate_same_candle_stop_long():
    df = _make_df(
        [
            {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 97, "close": 98},
        ]
    )
    trades = simulate_trades(df, "long", 100, 98, 105)
    assert len(trades) == 1
    assert trades[0].result == "loss"
    assert trades[0].exit_price == 98


def test_simulate_scratch_at_end():
    df = _make_df(
        [
            {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 99, "close": 100},
        ]
    )
    trades = simulate_trades(df, "long", 100, 98, 105)
    assert len(trades) == 1
    assert trades[0].result == "scratch"
    assert trades[0].exit_price == 100
    assert trades[0].r_multiple == 0.0


def test_simulate_invalid_levels():
    df = _make_df(
        [
            {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 99, "close": 100},
        ]
    )
    with pytest.raises(ValueError):
        simulate_trades(df, "long", 100, 101, 105)


def test_compute_metrics():
    trades = [
        Trade(direction="long", entry_price=100, stop_loss=98, target_price=104, exit_price=104, result="win", r_multiple=2.0),
        Trade(direction="long", entry_price=100, stop_loss=98, target_price=104, exit_price=98, result="loss", r_multiple=-1.0),
        Trade(direction="long", entry_price=100, stop_loss=98, target_price=104, exit_price=104, result="win", r_multiple=2.0),
    ]
    metrics = compute_metrics(trades)
    assert metrics.total_signals == 3
    assert metrics.win_count == 2
    assert metrics.loss_count == 1
    assert metrics.win_rate == pytest.approx(2 / 3)
    assert metrics.avg_rr == pytest.approx(1.0)
    assert metrics.profit_factor == pytest.approx(4.0)


def test_compute_metrics_empty():
    metrics = compute_metrics([])
    assert metrics.total_signals == 0
    assert metrics.win_rate == 0.0


def test_compute_metrics_max_drawdown():
    trades = [
        Trade(direction="long", entry_price=100, stop_loss=98, target_price=104, exit_price=104, result="win", r_multiple=2.0),
        Trade(direction="long", entry_price=100, stop_loss=98, target_price=104, exit_price=98, result="loss", r_multiple=-1.0),
        Trade(direction="long", entry_price=100, stop_loss=98, target_price=104, exit_price=98, result="loss", r_multiple=-1.0),
    ]
    metrics = compute_metrics(trades)
    # Equity: 2 -> 1 -> 0. Peak 2, trough 0, drawdown 2.
    assert metrics.max_drawdown == pytest.approx(2.0)
