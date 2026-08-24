"""Audit T5: hyperopt parameters ``buy_atr_mult`` and ``sell_trailing_stop``
must actually influence the strategy. The previous version declared both
but never read them in ``populate_entry_trend`` / ``bot_loop_start``.

Audit T6: translator must emit real signal logic, not the old
``dataframe['buy'] = 0`` stubs.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.services.freqtrade.translator import (
    TranslatorConfig,
    translate,
)
from app.domain.signal_schemas import HarmonicSignal
from app.strategies.trend_rsi_strategy import TrendRSI


def test_buy_atr_mult_filters_low_volatility_bars():
    """When buy_atr_mult is high, low-volatility bars are excluded from entries."""
    # Build 200 bars of constant close (low ATR) plus a few high-vol bars.
    n = 200
    close = pd.Series([100.0] * n)
    # Inject a few large moves to create ATR.
    close.iloc[10] = 110.0
    close.iloc[20] = 90.0
    df = pd.DataFrame({
        "open":   close,
        "high":   close + 1.0,
        "low":    close - 1.0,
        "close":  close,
        "volume": pd.Series([1.0] * n),
    })

    # freqtrade's IStrategy requires a config; pass an empty dict for unit
    # testing — populate_indicators doesn't read config.
    strat = TrendRSI(config={})
    out = strat.populate_indicators(df.copy(), {})
    assert "atr_pct" in out.columns
    assert "atr_min_pct" in out.columns
    # atr_min_pct = 0.005 * buy_atr_mult.value (default 1.0) → 0.005.
    assert float(out["atr_min_pct"].iloc[0]) == pytest.approx(0.005)

    # Raising buy_atr_mult to an extreme value should filter out the
    # low-volatility bars (atr_pct ≈ 0) and keep only the high-volatility
    # ones. We can't directly assert on enter_long (depends on RSI cross)
    # without forcing RSI signals, so verify that the threshold rose and
    # that the indicator columns compare as expected.
    strat.buy_atr_mult.value = 50.0
    out2 = strat.populate_indicators(df.copy(), {})
    assert float(out2["atr_min_pct"].iloc[0]) == pytest.approx(0.25)
    # Most bars should fail the atr_pct >= atr_min_pct filter (low-vol bars
    # have atr_pct ≈ 0). The two injected spikes should pass.
    passes = (out2["atr_pct"] >= out2["atr_min_pct"]).sum()
    assert passes < n // 2, (
        f"buy_atr_mult=50 should filter most low-vol bars; got {passes}/{n}"
    )


def test_sell_trailing_stop_is_bound_to_trailing_class_attr():
    """``bot_loop_start`` syncs ``self.trailing_stop`` to ``sell_trailing_stop.value``."""
    import datetime

    strat = TrendRSI(config={})
    # Set hyperopt parameter to True.
    strat.sell_trailing_stop.value = True
    strat.bot_loop_start(datetime.datetime.utcnow())
    assert strat.trailing_stop is True

    strat.sell_trailing_stop.value = False
    strat.bot_loop_start(datetime.datetime.utcnow())
    assert strat.trailing_stop is False


def test_translator_emits_real_signals_not_stubs():
    """Audit T6: pattern-mode translation produces a strategy file with
    real entry/exit logic — not the old ``dataframe['buy'] = 0`` stubs."""
    sig = HarmonicSignal(
        pattern_type="Gartley",
        entry_price=100.0,
        exit_price=110.0,
        stop_loss=95.0,
        zrpc_price=99.5,
        confidence=0.78,
        regime="bullish",
    )
    out_path = translate(
        sig,
        TranslatorConfig(timeframe="1h", can_short=False, stoploss=-0.05),
    )
    assert out_path.exists()
    src = out_path.read_text()

    # Old stubs are gone.
    assert "dataframe['buy'] = 0" not in src
    assert "dataframe['sell'] = 0" not in src
    # New entry/exit logic present.
    assert "zrpc_touch" in src
    assert "enter_long" in src
    assert "exit_long" in src
    assert "custom_stoploss" in src
    # Frozen signal levels are baked in.
    assert "ENTRY_PRICE = 100.0" in src
    assert "TP1_PRICE = 110.0" in src
    assert "STOP_PRICE = 95.0" in src
