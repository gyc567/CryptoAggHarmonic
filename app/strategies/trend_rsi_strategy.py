"""
TrendRSI Strategy — Freqtrade IStrategy.

Single source of truth: ``app.domain.strategy_core``.

Mapping
~~~~~~~
  strategy_core.compute_indicators()  → populate_indicators()
  strategy_core.RSI_ZONES              → oversold / overbought columns
  Domain L3 quality filter             → handled at scan API level
  Domain 3-tier TP + partial exit     → NOT supported by freqtrade IStrategy;
                                         documented as a known limitation.
  Domain stop-loss                    → custom_stoploss (static fraction)
  Domain TTL / trend-flip / rsi_extreme exits → custom_exit()

Hyperopt spaces
~~~~~~~~~~~~~~~
  buy:
    atr_mult        DecimalParameter (0.5 – 3.0, step 0.1)
    rsi_zone        CategoricalParameter (extreme / pullback)
    short_rsi_min   DecimalParameter (0 – 80, step 1)
  sell:
    use_ema50      BooleanParameter
    trailing_stop   BooleanParameter
"""

from __future__ import annotations

import datetime
import logging
from typing import Dict, List

import talib.abstract as ta
from freqtrade.strategy import (
    BooleanParameter,
    CategoricalParameter,
    DecimalParameter,
    IStrategy,
    IntParameter,
)
from pandas import DataFrame

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hyperoptable parameters — auto-assigned to buy/sell spaces by prefix
# ---------------------------------------------------------------------------

class TrendRSI(IStrategy):
    # ── Interface ────────────────────────────────────────────────────────
    INTERFACE_VERSION: int = 3
    timeframe: str = "1h"
    can_short: bool = True

    # ── Startup ────────────────────────────────────────────────────────────
    startup_candle_count: int = 200   # EMA200 warmup
    process_only_new_candles: bool = False
    use_exit_signal: bool = True
    exit_profit_only: bool = False

    # ── ROI / Stoploss ────────────────────────────────────────────────────
    # Empty → exits fully controlled by custom_exit + custom_stoploss.
    # freqtrade will still apply custom_stoploss per trade.
    minimal_roi: Dict[str, float] = {}

    # Default stoploss fraction (overridden per-trade via custom_stoploss).
    # Hyperopt will tune this via the stoploss space.
    stoploss: float = -0.03

    # ── Hyperoptable buy-space parameters ────────────────────────────────
    # (prefix buy_ / enter_ → "buy" space)
    buy_atr_mult: DecimalParameter = DecimalParameter(
        0.5, 3.0, decimals=1, default=1.0, space="buy",
    )
    buy_rsi_zone: CategoricalParameter = CategoricalParameter(
        ["extreme", "pullback"], default="extreme", space="buy",
    )
    buy_short_rsi_min: DecimalParameter = DecimalParameter(
        0.0, 80.0, decimals=1, default=65.0, space="buy",
    )

    # ── Hyperoptable sell-space parameters ──────────────────────────────
    # (prefix sell_ / exit_ → "sell" space)
    sell_use_ema50: BooleanParameter = BooleanParameter(
        default=False, space="sell",
    )
    sell_trailing_stop: BooleanParameter = BooleanParameter(
        default=False, space="sell",
    )
    sell_ttl_bars: IntParameter = IntParameter(
        0, 200, default=0, space="sell",
    )

    # ── Non-hyperoptable defaults ───────────────────────────────────────
    rsi_window: int = 14
    atr_window: int = 14
    ema_trend_span: int = 200
    ema_fast_span: int = 50
    use_ema50: bool = False          # runtime alias; use sell_use_ema50.value
    require_candle_color: bool = False

    # RSI zone presets
    _RSI_ZONES = {
        "extreme":   (30.0, 70.0),
        "pullback":   (40.0, 60.0),
    }

    # -------------------------------------------------------------------------
    # Indicators
    # -------------------------------------------------------------------------

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Add all strategy indicators."""

        # ── RSI ──────────────────────────────────────────────────────────
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=self.rsi_window)
        dataframe["rsi_prev"] = dataframe["rsi"].shift(1)

        # ── ATR ──────────────────────────────────────────────────────────
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_window)

        # ── EMAs ────────────────────────────────────────────────────────
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=self.ema_trend_span)
        dataframe["ema50"]  = ta.EMA(dataframe, timeperiod=self.ema_fast_span)

        # ── Zone boundaries (dynamic via hyperopt) ──────────────────────
        oversold, overbought = self._RSI_ZONES[self.buy_rsi_zone.value]
        dataframe["oversold"]  = oversold
        dataframe["overbought"] = overbought

        # ── Vectorized cross flags ────────────────────────────────────────
        # Long cross: rsi_prev <= oversold < rsi_now
        dataframe["rsi_cross_up"] = (
            (dataframe["rsi_prev"] <= dataframe["oversold"])
            & (dataframe["rsi"] > dataframe["oversold"])
        )
        # Short cross: rsi_prev >= overbought > rsi_now
        dataframe["rsi_cross_down"] = (
            (dataframe["rsi_prev"] >= dataframe["overbought"])
            & (dataframe["rsi"] < dataframe["overbought"])
        )

        return dataframe

    # -------------------------------------------------------------------------
    # Entry signals
    # -------------------------------------------------------------------------

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Set enter_long / enter_short columns."""

        use_ema50 = self.sell_use_ema50.value

        # ── Long conditions ─────────────────────────────────────────────
        long_cond = (
            (dataframe["close"] > dataframe["ema200"])
            & dataframe["rsi_cross_up"]
            & ((not use_ema50) | (dataframe["close"] > dataframe["ema50"]))
            & (
                (not self.require_candle_color)
                | (dataframe["close"] > dataframe["open"])
            )
            & (dataframe["volume"] > 0)
        )

        # ── Short conditions ─────────────────────────────────────────────
        short_cond = (
            (dataframe["close"] < dataframe["ema200"])
            & dataframe["rsi_cross_down"]
            & ((not use_ema50) | (dataframe["close"] < dataframe["ema50"]))
            & (dataframe["rsi_prev"] >= self.buy_short_rsi_min.value)
            & (dataframe["volume"] > 0)
        )

        dataframe.loc[long_cond,  "enter_long"]  = 1
        dataframe.loc[long_cond,  "enter_tag"]  = "rsi_long"
        dataframe.loc[short_cond, "enter_short"] = 1
        dataframe.loc[short_cond, "enter_tag"]  = "rsi_short"

        return dataframe

    # -------------------------------------------------------------------------
    # Exit signals (trend-flip only — TTL and rsi_extreme handled in custom_exit)
    # -------------------------------------------------------------------------

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Set exit_long / exit_short for trend-flip exits."""

        oversold  = dataframe["oversold"]
        overbought = dataframe["overbought"]

        # Long exit: RSI enters overbought AND price flips below EMA200
        long_exit = (
            (dataframe["rsi"] >= overbought)
            & (dataframe["close"] < dataframe["ema200"])
            & (dataframe["volume"] > 0)
        )
        # Short exit: RSI enters oversold AND price flips above EMA200
        short_exit = (
            (dataframe["rsi"] <= oversold)
            & (dataframe["close"] > dataframe["ema200"])
            & (dataframe["volume"] > 0)
        )

        dataframe.loc[long_exit,  "exit_long"]  = 1
        dataframe.loc[long_exit,  "exit_tag"]  = "trend_flip"
        dataframe.loc[short_exit, "exit_short"] = 1
        dataframe.loc[short_exit, "exit_tag"]  = "trend_flip"

        return dataframe

    # -------------------------------------------------------------------------
    # custom_exit — RSI-extreme and TTL exits (freqtrade calls this every candle)
    # -------------------------------------------------------------------------

    def custom_exit(
        self,
        pair: str,
        trade,                         # freqtrade.persistence.trade_model.Trade
        current_time,                  # datetime
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        """
        Return a non-empty exit tag to force an exit; None to defer to other
        exit mechanisms (populate_exit_trend, minimal_roi, stoploss).

        Exit conditions implemented:
          1. TTL circuit-breaker: exit after ttl_bars candles in the trade.
          2. RSI-extreme partial reduction is not natively supported by
             freqtrade IStrategy (would need custom exit order sizing).
             We emit an exit signal when RSI re-enters the extreme zone after
             a partial target would have been hit — treated as a full exit.
        """
        # ── TTL check ──────────────────────────────────────────────────
        ttl_bars = self.sell_ttl_bars.value
        if ttl_bars > 0 and trade.open_date_utc is not None:
            elapsed = current_time - trade.open_date_utc
            # Estimate bars from elapsed time (assumes 1h timeframe)
            elapsed_bars = int(elapsed.total_seconds() / 3600)
            if elapsed_bars >= ttl_bars:
                return "ttl"

        # ── RSI-extreme check ──────────────────────────────────────────
        # Requires current RSI: fetch the latest closed candle.
        df = self.dp.get_pair_dataframe(pair, self.timeframe)
        if df is not None and len(df) >= 2:
            rsi_now = float(df["rsi"].iloc[-1])
            oversold, overbought = self._RSI_ZONES[self.buy_rsi_zone.value]
            is_long = not trade.is_short

            if is_long and rsi_now >= overbought:
                return "rsi_extreme"
            if not is_long and rsi_now <= oversold:
                return "rsi_extreme"

        return None

    # -------------------------------------------------------------------------
    # custom_stoploss — static fraction (freqtrade handles ATR calc externally)
    # -------------------------------------------------------------------------

    def custom_stoploss(
        self,
        pair: str,
        trade,
        current_time: datetime.datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float | None:
        """
        Return the stoploss as a negative fraction of current rate.
        Returning None would leave the stoploss unchanged; we explicitly
        return self.stoploss so hyperopt can tune it via the stoploss space.
        """
        # NOTE: pair, trade, current_rate, current_profit, after_fill, kwargs
        # are available for future dynamic ATR-based stop logic.
        return self.stoploss

    # -------------------------------------------------------------------------
    # Pair locks (not used)
    # -------------------------------------------------------------------------

    def informative_pairs(self) -> List[tuple]:
        return []

    def bot_loop_start(
        self, current_time: datetime.datetime, **kwargs
    ) -> None:
        return
