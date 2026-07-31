"""Tests for bench.pipeline.stage2_backtest."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from bench.dataset.signal_record import empty_record
from bench.pipeline.stage2_backtest import _row_position, stage2_backtest


def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(datetime.fromisoformat(s).replace(tzinfo=timezone.utc))


def _df(rows: list[dict], start: str = "2026-01-01T00:00:00Z") -> pd.DataFrame:
    idx = pd.DatetimeIndex([_ts(start) + pd.Timedelta(hours=i) for i in range(len(rows))])
    return pd.DataFrame(rows, index=idx)


# ---------- _row_position ----------

def test_row_position_finds_existing_timestamp() -> None:
    df = _df([{"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1}])
    ts = df.index[0]
    assert _row_position(df, ts) == 0


def test_row_position_returns_none_for_missing_timestamp() -> None:
    df = _df([{"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1}])
    assert _row_position(df, _ts("2030-01-01T00:00:00Z")) is None


def test_row_position_returns_none_for_none() -> None:
    df = _df([{"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1}])
    assert _row_position(df, None) is None


def test_row_position_with_duplicate_index_returns_first_match() -> None:
    """Non-unique timestamp index → get_loc returns slice; we take [0]."""
    ts = _ts("2026-01-01T00:00:00Z")
    idx = pd.DatetimeIndex([ts, ts, _ts("2026-01-01T01:00:00Z")])
    df = pd.DataFrame(
        [
            {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1},
            {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1},
            {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1},
        ],
        index=idx,
    )
    assert _row_position(df, ts) == 0


# ---------- stage2_backtest: validation ----------

def test_stage2_raises_when_tp1_missing() -> None:
    rec = empty_record(direction="long", entry_price=100, stop_price=95, tp1=None)
    df = _df([{"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1}])
    with pytest.raises(ValueError):
        stage2_backtest(rec, df)


def test_stage2_raises_when_entry_price_missing() -> None:
    rec = empty_record(direction="long", entry_price=None, stop_price=95, tp1=110)
    df = _df([{"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1}])
    with pytest.raises(ValueError):
        stage2_backtest(rec, df)


def test_stage2_raises_when_stop_price_missing() -> None:
    rec = empty_record(direction="long", entry_price=100, stop_price=None, tp1=110)
    df = _df([{"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1}])
    with pytest.raises(ValueError):
        stage2_backtest(rec, df)


def test_stage2_explicit_tp1_overrides_rec() -> None:
    rec = empty_record(direction="long", entry_price=100, stop_price=95, tp1=None)
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 100, "volume": 1},
        {"open": 100, "high": 105, "low": 99, "close": 100, "volume": 1},
    ])
    trade = stage2_backtest(rec, df, tp1=105)
    assert trade is not None
    assert rec.outcome == "tp1"


# ---------- stage2_backtest: outcome mapping ----------

def test_stage2_long_tp1_hit() -> None:
    """Price enters at 100, target=110, hits → outcome=tp1, r=2."""
    rec = empty_record(direction="long", entry_price=100, stop_price=95, tp1=110)
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1},  # entry triggers
        {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 1},  # TP hit
    ])
    trade = stage2_backtest(rec, df)
    assert trade is not None
    assert rec.outcome == "tp1"
    assert rec.r_multiple == pytest.approx(2.0)  # 10 / 5
    assert rec.bars_held == 2


def test_stage2_long_stoploss() -> None:
    rec = empty_record(direction="long", entry_price=100, stop_price=95, tp1=110)
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1},
        {"open": 100, "high": 100, "low": 94, "close": 95, "volume": 1},  # stop hit
    ])
    trade = stage2_backtest(rec, df)
    assert trade is not None
    assert rec.outcome == "stoploss"
    assert rec.r_multiple == pytest.approx(-1.0)


def test_stage2_short_tp1_hit() -> None:
    rec = empty_record(direction="short", entry_price=100, stop_price=105, tp1=90)
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1},
        {"open": 100, "high": 100, "low": 90, "close": 91, "volume": 1},  # TP hit (short)
    ])
    trade = stage2_backtest(rec, df)
    assert trade is not None
    assert rec.outcome == "tp1"
    assert rec.r_multiple == pytest.approx(2.0)  # 10 / 5


def test_stage2_short_stoploss() -> None:
    rec = empty_record(direction="short", entry_price=100, stop_price=105, tp1=90)
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1},
        {"open": 100, "high": 106, "low": 100, "close": 105, "volume": 1},  # stop hit (short)
    ])
    trade = stage2_backtest(rec, df)
    assert trade is not None
    assert rec.outcome == "stoploss"
    assert rec.r_multiple == pytest.approx(-1.0)


def test_stage2_breakeven_exit_at_end_of_data() -> None:
    """Entry triggers, no stop/target hit, scratch at end → breakeven."""
    rec = empty_record(direction="long", entry_price=100, stop_price=95, tp1=110)
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1},
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1},  # no touch
    ])
    trade = stage2_backtest(rec, df)
    assert trade is not None
    assert rec.outcome == "breakeven"
    assert rec.r_multiple == 0.0
    assert rec.bars_held == 2


def test_stage2_no_entry_returns_none_and_clears_outcome() -> None:
    """If price never enters (low > entry for long), no trade → outcome=None."""
    rec = empty_record(direction="long", entry_price=100, stop_price=95, tp1=110)
    df = _df([
        {"open": 101, "high": 102, "low": 100.5, "close": 101, "volume": 1},  # no entry
    ])
    trade = stage2_backtest(rec, df)
    assert trade is None
    assert rec.outcome is None
    assert rec.r_multiple is None
    assert rec.bars_held is None


def test_stage2_populates_trade_metrics_on_win() -> None:
    rec = empty_record(direction="long", entry_price=100, stop_price=95, tp1=110, atr_at_entry=2.0)
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 100},
    ])
    stage2_backtest(rec, df)
    # MAE/MFE should be populated by apply_trade_metrics
    assert rec.mae is not None
    assert rec.mfe is not None
    assert rec.callback_depth is not None
    assert rec.price_efficiency is not None


def test_stage2_populates_trade_metrics_on_loss() -> None:
    rec = empty_record(direction="long", entry_price=100, stop_price=95, tp1=110, atr_at_entry=2.0)
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 100, "low": 94, "close": 95, "volume": 100},
    ])
    stage2_backtest(rec, df)
    assert rec.mae is not None and rec.mae > 0
    assert rec.price_efficiency == 0.0  # stoploss → 0


def test_stage2_raises_on_invalid_trade_entry_exit() -> None:
    """If simulate_trades returns a trade but timestamps don't resolve in
    the forward_df, we should raise loudly rather than silently miscount
    bars_held. We trigger this by mocking _row_position via monkeypatch."""
    from unittest.mock import patch
    rec = empty_record(direction="long", entry_price=100, stop_price=95, tp1=110)
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1},
        {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 1},
    ])
    with patch("bench.pipeline.stage2_backtest._row_position", return_value=None):
        with pytest.raises(ValueError, match="could not resolve"):
            stage2_backtest(rec, df)
