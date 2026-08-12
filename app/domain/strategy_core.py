"""
strategy_core — shared pure logic for TrendRSI.

All functions here are:
  - Pure: no I/O, no side-effects
  - Freqtrade-independent: no imports from freqtrade
  - Deterministic: same input → same output

This module is the single source of truth for signal-detection logic.
Both the real-time scan API and the Freqtrade IStrategy call into here.

Architecture
~~~~~~~~~~~~
  rsi_trend.py          (API compat wrapper)
        ↓
  strategy_core.py       (Source of Truth)
        ↓
  trend_rsi_strategy.py  (Freqtrade IStrategy adapter)

Classes
~~~~~~~
  Signal  — entry signal with price/stop/target/quality

Functions
~~~~~~~~~
  compute_indicators(df, ...)    — add EMA/RSI/ATR columns
  detect_signals_core(df, ...)     — scan for entry signals → [Signal]
  current_state_core(df)           — latest trend/momentum snapshot
  signal_quality(...)             — 0-100 quality heuristic

Constants
~~~~~~~~~
  RSI_WINDOW, ATR_WINDOW, EMA_TREND_SPAN, EMA_FAST_SPAN
  OVERSOLD, OVERBOUGHT, PULLBACK_OVERSOLD, PULLBACK_OVERBOUGHT
  RSI_ZONES, LONG, SHORT, WARMUP_BARS
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RSI_WINDOW: int = 14
ATR_WINDOW: int = 14
EMA_TREND_SPAN: int = 200
EMA_FAST_SPAN: int = 50
OVERSOLD: float = 30.0
OVERBOUGHT: float = 70.0
PULLBACK_OVERSOLD: float = 40.0
PULLBACK_OVERBOUGHT: float = 60.0
REWARD_RISK: float = 2.0
# Bars before EMA200 is stable
WARMUP_BARS: int = EMA_TREND_SPAN

RSI_ZONES: dict[str, tuple[float, float]] = {
    "extreme": (OVERSOLD, OVERBOUGHT),
    "pullback": (PULLBACK_OVERSOLD, PULLBACK_OVERBOUGHT),
}

LONG: Literal["long"] = "long"
SHORT: Literal["short"] = "short"


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    """A single entry signal produced by the strategy."""

    direction: str           # LONG | SHORT
    entry_price: float
    stop_loss: float
    target_price: float
    atr: float
    rsi: float
    rsi_prev: float
    quality_score: float    # 0-100
    time: str               # ISO timestamp or ""
    index: int              # positional bar index within df

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Indicator calculations
# ---------------------------------------------------------------------------

def ema_series(closes: pd.Series, span: int) -> pd.Series:
    """Exponential moving average (Wilder-style span)."""
    return closes.ewm(span=span, adjust=False).mean()


def rsi_series(closes: pd.Series, window: int = RSI_WINDOW) -> pd.Series:
    """Wilder RSI series."""
    delta = closes.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    # Pure-gain edge case
    rsi = rsi.where(~((gain > 0) & (loss == 0)), 100.0)
    return rsi


def atr_series(df: pd.DataFrame, window: int = ATR_WINDOW) -> pd.Series:
    """Average True Range (simple rolling mean of True Range)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window).mean()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a copy of ``df`` with strategy indicator columns appended.

    Columns added: ema200, ema50, rsi, rsi_prev, atr
    """
    out = df.copy()
    closes = out["close"].astype(float)
    out["ema200"] = ema_series(closes, EMA_TREND_SPAN)
    out["ema50"]  = ema_series(closes, EMA_FAST_SPAN)
    out["rsi"]    = rsi_series(closes)
    out["rsi_prev"] = out["rsi"].shift(1)
    out["atr"]     = atr_series(out)
    return out


# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------

def signal_quality(
    direction: str,
    close: float,
    ema200: float,
    ema50: float,
    rsi: float,
    rsi_prev: float,
    atr: float,
    open_price: float,
) -> float:
    """
    Heuristic 0-100 signal quality score.

    Components (total 100 pts max):
      - Trend displacement from EMA200, normalised by ATR  (≤40 pts)
      - EMA50 alignment with direction                     (20 pts)
      - RSI momentum (size of the cross)                  (≤25 pts)
      - Candle colour confirmation                        (15 pts)
    """
    if atr <= 0 or pd.isna(atr):
        return 0.0

    # Trend displacement (up to 40 pts)
    displacement = abs(close - ema200) / atr
    trend_score = min(displacement, 10.0) / 10.0 * 40.0

    # EMA50 alignment (20 pts)
    if direction == LONG:
        ema50_ok = close > ema50
    else:
        ema50_ok = close < ema50
    ema50_score = 20.0 if ema50_ok else 0.0

    # RSI momentum (up to 25 pts)
    rsi_momentum = abs(rsi - rsi_prev)
    rsi_score = min(rsi_momentum, 20.0) / 20.0 * 25.0

    # Candle colour (15 pts)
    if direction == LONG:
        color_ok = close > open_price
    else:
        color_ok = close < open_price
    color_score = 15.0 if color_ok else 0.0

    return min(trend_score + ema50_score + rsi_score + color_score, 100.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bar_time(df: pd.DataFrame, i: int) -> str:
    """Extract ISO timestamp string for bar i."""
    if "dts" in df.columns:
        val = df["dts"].iloc[i]
        try:
            return pd.Timestamp(val).isoformat()
        except (ValueError, TypeError):
            return str(val)
    try:
        return pd.Timestamp(df.index[i]).isoformat()
    except (ValueError, TypeError, IndexError):
        return ""


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

def detect_signals_core(
    df: pd.DataFrame,
    use_ema50: bool = False,
    require_candle_color: bool = False,
    atr_mult: float = 1.0,
    rsi_zone: str = "extreme",
    reward_risk: float = REWARD_RISK,
    min_quality_score: float = 0.0,
    short_rsi_min: float = 65.0,
) -> list[Signal]:
    """
    Scan ``df`` for entry signals.

    Long:  close > EMA200 and RSI crosses up through zone boundary.
    Short: close < EMA200 and RSI crosses down through zone boundary,
           with RSI_prev >= short_rsi_min.

    Parameters
    ----------
    df: DataFrame with columns open/high/low/close and optional dts.
    use_ema50: require close > EMA50 for longs (and < for shorts).
    require_candle_color: require bullish candle for longs.
    atr_mult: ATR multiplier for stop placement.
    rsi_zone: "extreme" (30/70) or "pullback" (40/60).
    reward_risk: reward-to-risk ratio for target placement.
    min_quality_score: discard signals below this quality (0-100).
    short_rsi_min: minimum RSI_prev for short signals (0 = off).
    """
    if len(df) <= WARMUP_BARS:
        return []

    data = compute_indicators(df)
    oversold, overbought = RSI_ZONES.get(rsi_zone, RSI_ZONES["extreme"])
    min_qs = max(0.0, min(min_quality_score, 100.0))
    signals: list[Signal] = []

    for i in range(WARMUP_BARS, len(data)):
        row = data.iloc[i]
        rsi_now  = float(row["rsi"])
        rsi_prev = float(row["rsi_prev"]) if not pd.isna(row["rsi_prev"]) else float("nan")
        atr      = float(row["atr"])       if not pd.isna(row["atr"])       else float("nan")

        if pd.isna(rsi_now) or pd.isna(rsi_prev) or pd.isna(atr):
            continue

        close = float(row["close"])
        crossed_up   = (rsi_prev <= oversold)  and (rsi_now > oversold)
        crossed_down = (rsi_prev >= overbought) and (rsi_now < overbought)

        if not (crossed_up or crossed_down):
            continue

        # ── Long entry ───────────────────────────────────────────────
        if crossed_up and close > float(row["ema200"]):
            if use_ema50 and not close > float(row["ema50"]):
                continue
            if require_candle_color and not close > float(row["open"]):
                continue
            stop = float(row["low"]) - atr_mult * atr
            risk = close - stop
            if risk <= 0:
                continue
            qs = signal_quality(
                LONG, close,
                float(row["ema200"]), float(row["ema50"]),
                rsi_now, rsi_prev, atr, float(row["open"]),
            )
            signals.append(Signal(
                direction=LONG,
                entry_price=close,
                stop_loss=stop,
                target_price=close + reward_risk * risk,
                atr=atr,
                rsi=rsi_now,
                rsi_prev=rsi_prev,
                quality_score=qs,
                time=_bar_time(data, i),
                index=i,
            ))

        # ── Short entry ──────────────────────────────────────────────
        elif crossed_down and close < float(row["ema200"]):
            if use_ema50 and not close < float(row["ema50"]):
                continue
            if require_candle_color and not close < float(row["open"]):
                continue
            if short_rsi_min > 0 and rsi_prev < short_rsi_min:
                continue
            stop = float(row["high"]) + atr_mult * atr
            risk = stop - close
            if risk <= 0:
                continue
            qs = signal_quality(
                SHORT, close,
                float(row["ema200"]), float(row["ema50"]),
                rsi_now, rsi_prev, atr, float(row["open"]),
            )
            signals.append(Signal(
                direction=SHORT,
                entry_price=close,
                stop_loss=stop,
                target_price=close - reward_risk * risk,
                atr=atr,
                rsi=rsi_now,
                rsi_prev=rsi_prev,
                quality_score=qs,
                time=_bar_time(data, i),
                index=i,
            ))

    return [s for s in signals if s.quality_score >= min_qs]


# ---------------------------------------------------------------------------
# Current state snapshot
# ---------------------------------------------------------------------------

def current_state_core(df: pd.DataFrame) -> dict | None:
    """
    Return the latest bar's trend/momentum snapshot.

    Returns None if df has fewer rows than WARMUP_BARS.
    """
    if len(df) <= WARMUP_BARS:
        return None

    data = compute_indicators(df)
    row  = data.iloc[-1]
    close  = float(row["close"])
    ema200 = float(row["ema200"])
    atr    = float(row["atr"]) if not pd.isna(row["atr"]) else None

    if close > ema200:
        trend = "bullish"
    elif close < ema200:
        trend = "bearish"
    else:
        trend = "neutral"

    deviation_pct = (close - ema200) / ema200 * 100 if ema200 else 0.0
    entangled = atr is not None and abs(close - ema200) < 0.5 * atr

    return {
        "time": _bar_time(data, len(data) - 1),
        "close": close,
        "ema200": ema200,
        "ema50": float(row["ema50"]),
        "rsi": float(row["rsi"]) if not pd.isna(row["rsi"]) else None,
        "atr": atr,
        "trend": trend,
        "deviation_pct": deviation_pct,
        "entangled": entangled,
    }
