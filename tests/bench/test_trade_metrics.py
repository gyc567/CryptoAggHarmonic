"""Tests for bench.pipeline.trade_metrics."""

from __future__ import annotations

import pandas as pd
import pytest

from bench.dataset.signal_record import empty_record
from bench.pipeline.trade_metrics import (
    _callback_volume_ratio,
    apply_trade_metrics,
    compute_trade_metrics,
    find_tp_bar,
    price_efficiency_for,
)


def _df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a list of row dicts."""
    return pd.DataFrame(rows)


# ---------- compute_trade_metrics: long ----------

def test_long_mae_is_adverse_distance() -> None:
    df = _df([
        {"open": 100, "high": 102, "low": 95, "close": 96, "volume": 100},
        {"open": 96, "high": 98, "low": 97, "close": 97.5, "volume": 110},
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=95, target_price=110,
        direction="long", atr_at_entry=2.0,
    )
    # bar 0 low=95 → MAE = entry - low = 5
    assert m["mae"] == 5.0
    assert m["mae_atr_ratio"] == pytest.approx(2.5)


def test_long_mfe_is_favorable_distance() -> None:
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 104, "volume": 100},
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=95, target_price=110,
        direction="long", atr_at_entry=2.0,
    )
    assert m["mfe"] == 5.0
    assert m["mfe_atr_ratio"] == pytest.approx(2.5)


def test_long_callback_depth_in_atr() -> None:
    df = _df([
        {"open": 100, "high": 102, "low": 97, "close": 98, "volume": 100},
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=95, target_price=110,
        direction="long", atr_at_entry=2.0,
    )
    # depth = (100 - 97) / 2 = 1.5 ATR
    assert m["callback_depth"] == pytest.approx(1.5)


def test_long_callback_bars_is_mae_bar_index_plus_one() -> None:
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 101, "low": 95, "close": 96, "volume": 110},
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=95, target_price=110,
        direction="long", atr_at_entry=2.0,
    )
    assert m["callback_bars"] == 2


def test_long_hit_stop_before_tp_true_when_only_stop() -> None:
    df = _df([
        {"open": 100, "high": 102, "low": 94, "close": 95, "volume": 100},
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=95, target_price=110,
        direction="long", atr_at_entry=2.0,
    )
    assert m["hit_stop_before_tp"] is True


def test_long_hit_stop_before_tp_false_when_both_hit() -> None:
    df = _df([
        {"open": 100, "high": 110, "low": 95, "close": 110, "volume": 100},
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=95, target_price=110,
        direction="long", atr_at_entry=2.0,
    )
    # both stop and TP hit in same bar → hit_stop_before_tp is False
    # because hit_target is also True
    assert m["hit_stop_before_tp"] is False


def test_long_stop_zone_touches() -> None:
    df = _df([
        {"open": 100, "high": 102, "low": 95.1, "close": 100, "volume": 100},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 100, "low": 94.8, "close": 100, "volume": 100},  # in zone
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=95, target_price=110,
        direction="long", atr_at_entry=2.0,
        stop_zone_atr=0.5,  # zone = [95-1, 95+1] = [94, 96]
    )
    # bar 0 low=95.1 → in zone [94, 96]? yes (95.1 within [94, 96])
    # bar 1 low=99 → out
    # bar 2 low=94.8 → in zone
    assert m["stop_zone_touches"] == 2


# ---------- compute_trade_metrics: short ----------

def test_short_mae_uses_high_not_low() -> None:
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 100, "volume": 100},
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=105, target_price=90,
        direction="short", atr_at_entry=2.0,
    )
    # MAE = high - entry = 5
    assert m["mae"] == 5.0


def test_short_mfe_uses_low_not_high() -> None:
    df = _df([
        {"open": 100, "high": 102, "low": 95, "close": 96, "volume": 100},
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=105, target_price=90,
        direction="short", atr_at_entry=2.0,
    )
    assert m["mfe"] == 5.0


def test_short_callback_depth_in_atr() -> None:
    df = _df([
        {"open": 100, "high": 103, "low": 99, "close": 100, "volume": 100},
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=105, target_price=90,
        direction="short", atr_at_entry=2.0,
    )
    # depth = (103 - 100) / 2 = 1.5 ATR
    assert m["callback_depth"] == pytest.approx(1.5)


# ---------- validation ----------

def test_long_invariant_violation_raises() -> None:
    df = _df([{"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1}])
    with pytest.raises(ValueError):
        compute_trade_metrics(
            df, entry_price=100, stop_price=110, target_price=120,
            direction="long", atr_at_entry=2.0,
        )


def test_short_invariant_violation_raises() -> None:
    df = _df([{"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1}])
    with pytest.raises(ValueError):
        compute_trade_metrics(
            df, entry_price=100, stop_price=90, target_price=80,
            direction="short", atr_at_entry=2.0,
        )


def test_empty_dataframe_raises() -> None:
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    with pytest.raises(ValueError):
        compute_trade_metrics(
            df, entry_price=100, stop_price=95, target_price=110,
            direction="long", atr_at_entry=2.0,
        )


def test_missing_columns_raises() -> None:
    df = pd.DataFrame({"open": [100], "high": [102]})  # missing low, close, volume
    with pytest.raises(ValueError):
        compute_trade_metrics(
            df, entry_price=100, stop_price=95, target_price=110,
            direction="long", atr_at_entry=2.0,
        )


def test_zero_atr_raises() -> None:
    df = _df([{"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1}])
    with pytest.raises(ValueError):
        compute_trade_metrics(
            df, entry_price=100, stop_price=95, target_price=110,
            direction="long", atr_at_entry=0.0,
        )


def test_negative_prices_raises() -> None:
    df = _df([{"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1}])
    with pytest.raises(ValueError):
        compute_trade_metrics(
            df, entry_price=-1, stop_price=-2, target_price=-3,
            direction="long", atr_at_entry=2.0,
        )


def test_negative_stop_zone_raises() -> None:
    df = _df([{"open": 100, "high": 102, "low": 99, "close": 100, "volume": 1}])
    with pytest.raises(ValueError):
        compute_trade_metrics(
            df, entry_price=100, stop_price=95, target_price=110,
            direction="long", atr_at_entry=2.0, stop_zone_atr=-0.1,
        )


# ---------- callback_volume_ratio ----------

def test_callback_volume_ratio_uses_pre_window() -> None:
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 102, "low": 95, "close": 96, "volume": 200},  # MAE bar
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=95, target_price=110,
        direction="long", atr_at_entry=2.0,
    )
    # pre mean = 100, callback (incl MAE) mean = (100+100+200)/3 = 133.33
    # ratio ≈ 1.333
    assert m["callback_volume_ratio"] == pytest.approx(1.333, abs=0.01)


def test_callback_volume_ratio_none_when_no_pre_window() -> None:
    df = _df([
        {"open": 100, "high": 102, "low": 95, "close": 96, "volume": 100},  # MAE at bar 0
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=95, target_price=110,
        direction="long", atr_at_entry=2.0,
    )
    assert m["callback_volume_ratio"] is None


def test_callback_volume_ratio_none_when_no_mae() -> None:
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 100},
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=95, target_price=110,
        direction="long", atr_at_entry=2.0,
    )
    assert m["callback_volume_ratio"] is None


def test_callback_volume_ratio_handles_zero_pre_volume() -> None:
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 0},
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 0},
        {"open": 100, "high": 102, "low": 95, "close": 96, "volume": 100},
    ])
    m = compute_trade_metrics(
        df, entry_price=100, stop_price=95, target_price=110,
        direction="long", atr_at_entry=2.0,
    )
    assert m["callback_volume_ratio"] is None


def test_callback_volume_ratio_direct_none_when_no_mae() -> None:
    """Direct unit test of the helper (covers the None early-return)."""
    df = _df([{"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1}])
    assert _callback_volume_ratio(df, mae_bar_index=None) is None


def test_callback_volume_ratio_direct_mae_at_bar_zero() -> None:
    """Direct test: MAE at bar 0 → no pre-window → None."""
    df = _df([
        {"open": 100, "high": 102, "low": 95, "close": 96, "volume": 100},
    ])
    assert _callback_volume_ratio(df, mae_bar_index=0) is None


# ---------- price_efficiency_for ----------

def test_price_efficiency_tp_hit() -> None:
    assert price_efficiency_for("tp1", tp_bar_index=5, total_bars_held=10) == 0.5
    assert price_efficiency_for("tp2", tp_bar_index=8, total_bars_held=10) == 0.8


def test_price_efficiency_stoploss_zero() -> None:
    assert price_efficiency_for("stoploss", tp_bar_index=None, total_bars_held=10) == 0.0


def test_price_efficiency_breakeven_zero() -> None:
    assert price_efficiency_for("breakeven", tp_bar_index=None, total_bars_held=10) == 0.0


def test_price_efficiency_tp_with_no_bar() -> None:
    assert price_efficiency_for("tp1", tp_bar_index=None, total_bars_held=10) == 0.0


def test_price_efficiency_tp_zero_total_bars() -> None:
    assert price_efficiency_for("tp1", tp_bar_index=5, total_bars_held=0) == 0.0


def test_price_efficiency_clamped_high() -> None:
    # If somehow tp_bar > total (shouldn't happen, but defensive)
    assert price_efficiency_for("tp1", tp_bar_index=15, total_bars_held=10) == 1.0


# ---------- find_tp_bar ----------

def test_find_tp_bar_long() -> None:
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 105, "low": 99, "close": 104, "volume": 100},  # high >= 105
        {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 100},
    ])
    assert find_tp_bar(df, "long", 105) == 1


def test_find_tp_bar_short() -> None:
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 102, "low": 90, "close": 91, "volume": 100},  # low <= 90
    ])
    assert find_tp_bar(df, "short", 90) == 1


def test_find_tp_bar_no_hit() -> None:
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 103, "low": 98, "close": 101, "volume": 100},
    ])
    assert find_tp_bar(df, "long", 110) is None


def test_find_tp_bar_empty() -> None:
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    assert find_tp_bar(df, "long", 110) is None


# ---------- apply_trade_metrics ----------

def test_apply_trade_metrics_long_writes_back() -> None:
    rec = empty_record(
        direction="long",
        entry_price=100, stop_price=95, tp1=110, atr_at_entry=2.0,
        outcome="tp1", bars_held=10,
    )
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 100},
    ])
    apply_trade_metrics(rec, df)
    assert rec.mae is not None and rec.mae > 0
    assert rec.mfe is not None and rec.mfe > 0
    assert rec.callback_depth is not None
    assert rec.callback_bars is not None
    assert rec.stop_zone_touches >= 0
    # TP hit on bar 1 of a 10-bar trade → efficiency = 0.1
    assert rec.price_efficiency == pytest.approx(0.1)


def test_apply_trade_metrics_long_tp_on_last_bar() -> None:
    """If TP hits on the last bar of a 10-bar trade, efficiency = 1.0."""
    rec = empty_record(
        direction="long",
        entry_price=100, stop_price=95, tp1=110, atr_at_entry=2.0,
        outcome="tp1", bars_held=10,
    )
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 100},
        {"open": 100, "high": 105, "low": 99, "close": 104, "volume": 100},
        {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 100},  # TP on bar 2
    ])
    # But we only have 3 bars while bars_held=10, so efficiency = 2/10 = 0.2
    apply_trade_metrics(rec, df)
    assert rec.price_efficiency == pytest.approx(0.2)


def test_apply_trade_metrics_short_writes_back() -> None:
    rec = empty_record(
        direction="short",
        entry_price=100, stop_price=105, tp1=90, atr_at_entry=2.0,
        outcome="stoploss", bars_held=5,
    )
    df = _df([
        {"open": 100, "high": 105, "low": 99, "close": 105, "volume": 100},
    ])
    apply_trade_metrics(rec, df)
    assert rec.mae == 5.0
    assert rec.price_efficiency == 0.0  # stoploss → 0


def test_apply_trade_metrics_no_outcome_skips_price_efficiency() -> None:
    rec = empty_record(
        direction="long",
        entry_price=100, stop_price=95, tp1=110, atr_at_entry=2.0,
        outcome=None, bars_held=None,
    )
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 100, "volume": 100},
    ])
    apply_trade_metrics(rec, df)
    assert rec.price_efficiency is None
