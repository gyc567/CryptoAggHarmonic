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


# ---------------------------------------------------------------------------
# Audit T7: fees / slippage / funding realism
# ---------------------------------------------------------------------------


def test_zero_cost_equals_legacy():
    """With all knobs at zero the engine matches the original perfect-fill math."""
    df = _make_df([
        {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 99, "close": 100},
        {"dts": "2026-01-01 01:00", "open": 100, "high": 105, "low": 99, "close": 104},
    ])
    from app.services.vibe.backtest_engine import BacktestConfig
    trades = simulate_trades(df, "long", 100, 98, 105, config=BacktestConfig())
    assert len(trades) == 1
    assert trades[0].entry_price == pytest.approx(100.0)
    assert trades[0].exit_price == pytest.approx(105.0)
    assert trades[0].r_multiple == pytest.approx(2.5)  # (105-100)/(100-98)
    assert trades[0].fees_paid == pytest.approx(0.0)
    assert trades[0].funding_paid == pytest.approx(0.0)


def test_fees_reduce_r_multiple():
    """Round-trip fees debited from R."""
    df = _make_df([
        {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 99, "close": 100},
        {"dts": "2026-01-01 01:00", "open": 100, "high": 105, "low": 99, "close": 104},
    ])
    from app.services.vibe.backtest_engine import BacktestConfig
    cfg = BacktestConfig(fee_bps=10.0)  # 0.10% per side
    trades = simulate_trades(df, "long", 100, 98, 105, config=cfg)
    assert trades[0].fees_paid > 0
    assert trades[0].r_multiple < 2.5  # fees debited
    assert trades[0].fees_paid == pytest.approx(0.0010 * (trades[0].entry_price + trades[0].exit_price))


def test_slippage_pessimistic_for_long():
    """Long entry fills higher, target fills lower."""
    df = _make_df([
        {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 99, "close": 100},
        {"dts": "2026-01-01 01:00", "open": 100, "high": 105, "low": 99, "close": 104},
    ])
    from app.services.vibe.backtest_engine import BacktestConfig
    cfg = BacktestConfig(slippage_bps=20.0)  # 0.2%
    trades = simulate_trades(df, "long", 100, 98, 105, config=cfg)
    assert trades[0].entry_price > 100  # paid more
    assert trades[0].exit_price < 105  # received less (target -slip)


def test_slippage_pessimistic_for_short():
    """Short entry fills lower, target fills higher."""
    df = _make_df([
        {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 99, "close": 100},
        {"dts": "2026-01-01 01:00", "open": 100, "high": 101, "low": 95, "close": 96},
    ])
    from app.services.vibe.backtest_engine import BacktestConfig
    cfg = BacktestConfig(slippage_bps=20.0)
    trades = simulate_trades(df, "short", 100, 103, 95, config=cfg)
    assert trades[0].entry_price < 100  # received less
    assert trades[0].exit_price > 95  # paid more (target +slip for short)


def test_funding_accrues_per_bar_held():
    """Funding is debited once per bar the trade is open."""
    df = _make_df([
        {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 99, "close": 100},
        {"dts": "2026-01-01 01:00", "open": 100, "high": 105, "low": 99, "close": 104},
        {"dts": "2026-01-01 02:00", "open": 104, "high": 104.5, "low": 103, "close": 103.5},
    ])
    from app.services.vibe.backtest_engine import BacktestConfig
    cfg = BacktestConfig(funding_bps_per_8h=10.0, bar_hours=1.0)  # ~1.25 bps/bar
    trades = simulate_trades(df, "long", 100, 98, 105, config=cfg)
    assert trades[0].funding_paid > 0
    # 1 bar held (entry bar) + 1 bar while in trade = 2 bars
    expected = (10.0 / 10000.0) * (1.0 / 8.0) * 2 * trades[0].exit_price
    assert trades[0].funding_paid == pytest.approx(expected, rel=1e-3)


def test_compute_metrics_surfaces_totals():
    """Summary reports total fees / funding and the config used (audit T7)."""
    from app.services.vibe.backtest_engine import BacktestConfig
    trades = [
        Trade(direction="long", entry_price=100, stop_loss=98, target_price=104, exit_price=104, result="win", r_multiple=2.0,
              fees_paid=0.1, funding_paid=0.05),
        Trade(direction="long", entry_price=100, stop_loss=98, target_price=104, exit_price=98, result="loss", r_multiple=-1.0,
              fees_paid=0.1, funding_paid=0.05),
    ]
    cfg = BacktestConfig(fee_bps=10.0, funding_bps_per_8h=10.0)
    summary = compute_metrics(trades, config=cfg)
    assert summary.config_used == cfg
    assert summary.total_fees == pytest.approx(0.2)
    assert summary.total_funding == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# Audit T8: sample-size guardrail
# ---------------------------------------------------------------------------


def test_low_sample_flag_set_below_min_trades():
    trades = [
        Trade(direction="long", entry_price=100, stop_loss=98, target_price=104, exit_price=104, result="win", r_multiple=2.0),
    ]
    summary = compute_metrics(trades, min_trades=30)
    assert summary.is_low_sample is True
    assert summary.min_trades_required == 30


def test_low_sample_flag_unset_above_min_trades():
    trades = [
        Trade(direction="long", entry_price=100, stop_loss=98, target_price=104, exit_price=104, result="win", r_multiple=2.0)
        for _ in range(40)
    ]
    summary = compute_metrics(trades, min_trades=30)
    assert summary.is_low_sample is False


def test_invalid_leverage_rejected():
    from app.services.vibe.backtest_engine import BacktestConfig
    df = _make_df([
        {"dts": "2026-01-01 00:00", "open": 100, "high": 101, "low": 99, "close": 100},
    ])
    with pytest.raises(ValueError):
        simulate_trades(df, "long", 100, 98, 105, config=BacktestConfig(leverage=0))
