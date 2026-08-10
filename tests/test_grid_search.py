"""Tests for confluence weight grid-search calibration."""
import itertools

import pandas as pd
import pytest

from app.services.signal_engine import (
    _complete_weights,
    MAIN_WEIGHT_KEYS,
    grid_search_weights,
)
from app.config.tuning import TuningConstants
from scripts.backtest_harmonic_lib import BacktestSignalRecord

import dataclasses


def _make_df(n: int = 600) -> pd.DataFrame:
    """Deterministic trending data with some harmonic-ish structure."""
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    closes = [100.0 + i * 0.05 + (i % 5) * 0.2 for i in range(n)]
    df = pd.DataFrame(
        {
            "open": [c - 0.1 for c in closes],
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * n,
            "close_time": [int(t.timestamp()) for t in idx],
        },
        index=idx,
    )
    df["dts"] = idx
    return df


def test_complete_weights_sums_to_100():
    w5 = {"price_action": 25.0, "htf_trend": 25.0, "rsi": 15.0, "structure": 15.0, "macd": 10.0}
    full = _complete_weights(w5)
    assert abs(sum(full.values()) - 100.0) < 0.01
    assert full["funding"] == 10.0


def test_complete_weights_passes_tuning_validation():
    w5 = {"price_action": 20.0, "htf_trend": 20.0, "rsi": 20.0, "structure": 20.0, "macd": 10.0}
    full = _complete_weights(w5)
    # Must not raise (TuningConstants validates sum == 100 and key presence)
    dataclasses.replace(TuningConstants(), confluence_weights=full)


def test_grid_search_returns_best_and_results():
    df = _make_df()
    base = _complete_weights({"price_action": 25.0, "htf_trend": 25.0, "rsi": 15.0, "structure": 15.0, "macd": 10.0})
    alt = _complete_weights({"price_action": 20.0, "htf_trend": 20.0, "rsi": 20.0, "structure": 20.0, "macd": 10.0})
    out = grid_search_weights(
        df, "BTC/USDT", "1h",
        candidates=[base, alt],
        window=240, step=24, horizon=24,
    )
    assert "best_weights" in out
    assert "results" in out
    assert len(out["results"]) == 2
    for r in out["results"]:
        assert "win_rate" in r and "avg_r" in r and "n" in r
    # best_weights must be one of the input candidates
    assert out["best_weights"] in (base, alt)


def test_grid_search_requires_min_sample():
    """Candidates with fewer than 5 trades must not win."""
    df = _make_df(60)  # tiny dataset → likely < 5 trades per candidate
    base = _complete_weights({"price_action": 25.0, "htf_trend": 25.0, "rsi": 15.0, "structure": 15.0, "macd": 10.0})
    alt = _complete_weights({"price_action": 20.0, "htf_trend": 20.0, "rsi": 20.0, "structure": 20.0, "macd": 10.0})
    out = grid_search_weights(
        df, "BTC/USDT", "1h",
        candidates=[base, alt],
        window=60, step=10, horizon=12,
    )
    # Falls back to first candidate when nothing passes the sample gate
    assert out["best_weights"] == base
