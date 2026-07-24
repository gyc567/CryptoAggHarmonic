"""Unit tests for the trend-RSI strategy domain logic."""
from __future__ import annotations

import pandas as pd
import pytest

from app.domain.rsi_trend import (
    LONG,
    SHORT,
    StrategySignal,
    atr_series,
    current_state,
    detect_signals,
    ema_series,
    rsi_series,
)
from app.domain.rsi_trend_backtest import (
    EXIT_END,
    EXIT_PARTIAL_TARGET,
    EXIT_RSI_EXTREME,
    EXIT_STOP,
    EXIT_TARGET,
    EXIT_TREND_FLIP,
    run_backtest,
)


def make_df(closes: list[float], opens: list[float] | None = None) -> pd.DataFrame:
    """Build an OHLC DataFrame from closes; opens default to the prior close."""
    if opens is None:
        opens = [closes[0]] + closes[:-1]
    rows = {
        "open": opens,
        "close": closes,
        "high": [max(o, c) + 0.5 for o, c in zip(opens, closes)],
        "low": [min(o, c) - 0.5 for o, c in zip(opens, closes)],
    }
    return pd.DataFrame(rows)


def uptrend_then_dip(bounce_open: float | None = None) -> pd.DataFrame:
    """200-bar uptrend (close far above EMA200), sharp RSI<30 dip, bounce."""
    closes = [100.0 + i for i in range(200)]  # 100 -> 299
    closes += [284.0, 269.0, 254.0]  # violent dip: RSI < 30
    closes += [262.0]  # bounce: RSI crosses back up through 30
    opens = None
    if bounce_open is not None:
        opens = [closes[0]] + closes[:-1]
        opens[-1] = bounce_open
    return make_df(closes, opens)


def downtrend_then_rally() -> pd.DataFrame:
    """200-bar downtrend (close far below EMA200), sharp RSI>70 rally, drop."""
    closes = [300.0 - i for i in range(200)]  # 300 -> 101
    closes += [116.0, 131.0, 146.0]  # violent rally: RSI > 70
    closes += [138.0]  # pullback: RSI crosses back down through 70
    return make_df(closes)


# ---------------------------------------------------------------- indicators


def test_ema_series_matches_ewm():
    closes = pd.Series([1.0, 2.0, 3.0, 4.0])
    expected = closes.ewm(span=200, adjust=False).mean()
    pd.testing.assert_series_equal(ema_series(closes, 200), expected)


def test_rsi_series_all_gains_is_100():
    rsi = rsi_series(pd.Series([float(i) for i in range(1, 40)]))
    assert rsi.iloc[-1] == pytest.approx(100.0)


def test_rsi_series_all_losses_is_0():
    rsi = rsi_series(pd.Series([float(100 - i) for i in range(40)]))
    assert rsi.iloc[-1] == pytest.approx(0.0)


def test_atr_series_constant_range():
    df = make_df([100.0] * 30)
    atr = atr_series(df)
    # constant close -> flat candles with 1.0 total range each bar
    assert atr.iloc[-1] == pytest.approx(1.0)


# ------------------------------------------------------------ signal detection


def test_long_signal_fires_above_ema200():
    df = uptrend_then_dip()
    signals = detect_signals(df)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.direction == LONG
    assert sig.index == len(df) - 1
    assert sig.entry_price == pytest.approx(262.0)
    assert sig.stop_loss < sig.entry_price
    assert sig.target_price == pytest.approx(
        sig.entry_price + 2 * (sig.entry_price - sig.stop_loss)
    )


def test_long_signal_filtered_below_ema200():
    # Flat at 100 for 200 bars, crash, bounce: RSI crosses up but price is
    # below EMA200 -> trend filter must veto the signal.
    closes = [100.0] * 200 + [95.0, 90.0, 85.0, 97.0]
    signals = detect_signals(make_df(closes))
    assert signals == []


def test_short_signal_fires_below_ema200():
    df = downtrend_then_rally()
    signals = detect_signals(df)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.direction == SHORT
    assert sig.entry_price == pytest.approx(138.0)
    assert sig.stop_loss > sig.entry_price
    assert sig.target_price == pytest.approx(
        sig.entry_price - 2 * (sig.stop_loss - sig.entry_price)
    )


def test_no_signals_inside_warmup():
    closes = [100.0 + i for i in range(150)] + [140.0, 130.0, 120.0, 123.0]
    assert detect_signals(make_df(closes)) == []


def test_ema50_filter_vetoes_signal():
    df = uptrend_then_dip()
    assert detect_signals(df, use_ema50=False)
    # After the dip, close (262) sits below EMA50 of the recent highs.
    assert detect_signals(df, use_ema50=True) == []


def test_candle_color_filter_vetoes_signal():
    df = uptrend_then_dip(bounce_open=265.0)  # bearish candle (open > close 262)
    assert detect_signals(df, require_candle_color=False)
    assert detect_signals(df, require_candle_color=True) == []


def test_atr_mult_widens_stop():
    df = uptrend_then_dip()
    s1 = detect_signals(df, atr_mult=1.0)[0]
    s15 = detect_signals(df, atr_mult=1.5)[0]
    assert s15.stop_loss < s1.stop_loss


# ------------------------------------------------------------------ backtest


def make_signal(index: int = 0, direction: str = LONG, entry: float = 100.0,
                stop: float = 98.0, target: float = 104.0) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        entry_price=entry,
        stop_loss=stop,
        target_price=target,
        atr=1.0,
        rsi=35.0,
        time="t0",
        index=index,
    )


def test_backtest_stop_loss_exit():
    # rising bars keep close above EMA200; bar 3 low (96.5) hits stop 98
    df = make_df([100.0, 101.0, 102.0, 97.0])
    result = run_backtest(df, [make_signal()])
    trade = result.trades[0]
    assert trade.exit_reason == EXIT_STOP
    assert trade.exit_price == pytest.approx(98.0)
    assert trade.r_multiple == pytest.approx(-1.0)


def test_backtest_target_exit():
    df = make_df([100.0, 101.0, 105.0])  # bar 2 high (105.5) hits target 104
    result = run_backtest(df, [make_signal()])
    trade = result.trades[0]
    assert trade.exit_reason == EXIT_TARGET
    assert trade.r_multiple == pytest.approx(2.0)


def test_backtest_same_bar_stop_and_target_is_conservative():
    # One bar spans both stop and target -> assume stop first.
    df = make_df([100.0, 101.0], opens=[100.0, 96.0])
    df.loc[1, "low"] = 95.0
    df.loc[1, "high"] = 106.0
    result = run_backtest(df, [make_signal()])
    assert result.trades[0].exit_reason == EXIT_STOP
    assert result.trades[0].r_multiple == pytest.approx(-1.0)


def test_backtest_trend_flip_exit():
    # Rising prices then a crash bar: close drops below EMA200 -> exit.
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 90.0]
    df = make_df(closes)
    # stop far away so only the trend flip can trigger
    result = run_backtest(df, [make_signal(stop=80.0, target=140.0)])
    trade = result.trades[0]
    assert trade.exit_reason == EXIT_TREND_FLIP
    assert trade.exit_price == pytest.approx(90.0)
    assert trade.r_multiple == pytest.approx((90.0 - 100.0) / 20.0)


def test_backtest_end_of_data_scratch():
    df = make_df([100.0, 100.2, 100.1])
    result = run_backtest(df, [make_signal(stop=90.0, target=120.0)])
    trade = result.trades[0]
    assert trade.exit_reason == EXIT_END
    assert trade.exit_price == pytest.approx(100.1)


def test_backtest_overlapping_signals_are_skipped():
    df = make_df([100.0, 100.2, 100.1])
    signals = [make_signal(index=0), make_signal(index=1)]
    result = run_backtest(df, signals)
    assert result.trades_count == 1
    assert result.total_signals == 2


def test_backtest_partial_mode_target_reduce_then_breakeven():
    # Bar 2 hits the 1:2 target (close 50%, stop -> breakeven); RSI is pinned
    # at 100 (> 70, all-gain ramp) so half of the rest is reduced the same bar
    # at close 105; bar 4 crashes through the breakeven stop, flattening the
    # remaining 25%.
    closes = [100.0, 101.0, 105.0, 106.0, 80.0]
    df = make_df(closes)
    result = run_backtest(df, [make_signal()], partial_mode=True)
    trade = result.trades[0]
    assert trade.exit_reason == EXIT_STOP
    assert [p.reason for p in trade.partials] == [EXIT_PARTIAL_TARGET, EXIT_RSI_EXTREME]
    # 50% * 2R + 25% * 2.5R + 25% * 0R (breakeven)
    assert trade.r_multiple == pytest.approx(0.5 * 2.0 + 0.25 * 2.5)


def test_backtest_metrics_aggregation():
    df_win = make_df([100.0, 101.0, 105.0, 106.0])
    df = df_win  # one winning trade: +2R
    result = run_backtest(df, [make_signal()])
    assert result.win_count == 1
    assert result.win_rate == pytest.approx(1.0)
    assert result.total_r == pytest.approx(2.0)
    assert result.profit_factor == float("inf")
    assert result.max_drawdown_r == pytest.approx(0.0)


def test_backtest_profit_factor_and_drawdown():
    # Trade 1 wins +2R at target; trade 2 (far target) loses -1R at stop.
    # Rising bars in between keep close above EMA200 (no trend flip).
    closes = [100.0, 101.0, 105.0, 106.0, 107.0, 108.0, 96.0]
    df = make_df(closes)
    signals = [make_signal(index=0), make_signal(index=3, target=120.0)]
    result = run_backtest(df, signals)
    assert result.trades_count == 2
    assert result.profit_factor == pytest.approx(2.0)
    assert result.max_drawdown_r == pytest.approx(1.0)
    assert result.avg_r == pytest.approx(0.5)


# ------------------------------------------------------------ current state


def test_current_state_bullish():
    df = make_df([100.0 + i for i in range(250)])
    state = current_state(df)
    assert state is not None
    assert state["trend"] == "bullish"
    assert state["close"] > state["ema200"]
    assert state["deviation_pct"] > 0


def test_current_state_entangled():
    df = make_df([100.0] * 250)
    state = current_state(df)
    assert state is not None
    assert state["entangled"] is True


def test_current_state_insufficient_data():
    assert current_state(make_df([100.0] * 100)) is None
