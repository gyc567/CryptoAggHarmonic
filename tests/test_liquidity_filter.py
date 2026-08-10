"""Tests for the liquidity-sweep gate in discipline_filters."""
import pandas as pd
import pytest

from app.domain.signals import Candidate
from app.services.discipline_filters import evaluate


def _make_df(n: int = 30, base_vol: float = 1_000_000.0, d_vol: float | None = None) -> pd.DataFrame:
    """Uptrending candles; optionally surge volume at the last bar (D)."""
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(n)],
            "high": [100.0 + i * 0.1 + 0.5 for i in range(n)],
            "low": [100.0 + i * 0.1 - 0.5 for i in range(n)],
            "close": [100.0 + i * 0.1 for i in range(n)],
            "volume": [base_vol] * n,
            "close_time": [int(t.timestamp()) for t in idx],
        },
        index=idx,
    )
    df["dts"] = idx
    if d_vol is not None:
        df.loc[df.index[-1], "volume"] = d_vol
    return df


def _candidate(d_idx: int = 29) -> Candidate:
    return Candidate(
        family="XABCD",
        name="bat",
        bullish=True,
        formed=True,
        points=(110.0, 105.0, 108.0, 106.0, 100.0),
        completion_min=99.0,
        completion_max=101.0,
        times=(),
        indices=(0, 4, 8, 12, d_idx),
    )


def test_liquidity_sweep_flagged_when_d_volume_surges():
    """D-bar volume at 4x the 20-bar mean must set liquidity_sweep=True."""
    df = _make_df(d_vol=4_000_000.0)  # 4x base
    cand = _candidate(d_idx=29)
    result = evaluate(df, cand, current_price=100.5)
    assert result.metrics.liquidity_sweep is True


def test_liquidity_sweep_not_flagged_at_normal_volume():
    """Normal volume must not flag."""
    df = _make_df(d_vol=1_000_000.0)  # 1x base
    cand = _candidate(d_idx=29)
    result = evaluate(df, cand, current_price=100.5)
    assert result.metrics.liquidity_sweep is False


def test_liquidity_sweep_below_threshold_not_flagged():
    """2x (below 3x threshold) must not flag."""
    df = _make_df(d_vol=2_000_000.0)
    cand = _candidate(d_idx=29)
    result = evaluate(df, cand, current_price=100.5)
    assert result.metrics.liquidity_sweep is False


def test_liquidity_sweep_does_not_hard_reject():
    """A sweep flag must NOT flip passed to False (trap marker, not veto).

    passed is computed as ``not breached and not past_tp2`` and is
    deliberately independent of liquidity_sweep — the sweep only surfaces
    in metrics for downstream trap scoring.
    """
    from app.services import discipline_filters

    idx = pd.date_range("2026-01-01", periods=30, freq="h", tz="UTC")
    # Price sits in [101.5, 102.5]: above PRZ high (101, so no breach) and
    # below TP2 (~103.09 for A=105, entry=100, so no past_tp2).
    closes = [102.0 - (i % 2) * 0.4 for i in range(30)]
    df = pd.DataFrame(
        {
            "open": [c - 0.1 for c in closes],
            "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * 30,
            "close_time": [int(t.timestamp()) for t in idx],
        },
        index=idx,
    )
    df["dts"] = idx
    df.loc[df.index[-1], "volume"] = 5_000_000.0  # D-point surge
    cand = _candidate(d_idx=29)
    result = evaluate(df, cand, current_price=102.0)
    assert result.metrics.liquidity_sweep is True
    assert result.metrics.breached_stop is False
    assert result.metrics.past_tp2 is False
    assert result.passed is True  # sweep is a marker, not a veto


def test_liquidity_sweep_missing_indices_short_circuits():
    """Candidate without indices must not crash and not flag."""
    cand = _candidate(d_idx=29)
    cand = Candidate(
        family="XABCD", name="bat", bullish=True, formed=True,
        points=(110.0, 105.0, 108.0, 106.0, 100.0),
        completion_min=99.0, completion_max=101.0,
        times=(), indices=(),
    )
    df = _make_df(d_vol=5_000_000.0)
    result = evaluate(df, cand, current_price=100.5)
    assert result.metrics.liquidity_sweep is False
