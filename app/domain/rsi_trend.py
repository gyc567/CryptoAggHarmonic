"""Trend-RSI strategy domain logic (pure functions, no I/O).

Methodology: "trend defines direction, RSI defines timing".
- EMA200 is the trend filter: longs only above it, shorts only below it.
- RSI(14) leaving an extreme zone is the trigger:
    long  -> RSI crosses UP through 30 (leaving oversold)
    short -> RSI crosses DOWN through 70 (leaving overbought)
- Optional confirmations: candle color and/or EMA50 alignment.
- Stop: signal-bar low/high minus/plus ``atr_mult`` * ATR(14).
- First target: fixed 1:2 reward-to-risk.

Input DataFrame contract (same as the rest of the app):
columns ``open``, ``high``, ``low``, ``close`` and optionally ``dts``
(a datetime-like column used for signal timestamps).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

RSI_WINDOW = 14
ATR_WINDOW = 14
EMA_TREND_SPAN = 200
EMA_FAST_SPAN = 50
OVERSOLD = 30.0
OVERBOUGHT = 70.0
PULLBACK_OVERSOLD = 40.0
PULLBACK_OVERBOUGHT = 60.0
REWARD_RISK = 2.0
# Bars needed before EMA200 is meaningful; no signals inside the warm-up zone.
WARMUP_BARS = EMA_TREND_SPAN

# RSI entry-zone presets.  "extreme" is the original 30/70 mean-reversion rule;
# "pullback" uses shallower 40/60 zones to catch more trend pullbacks.
RSI_ZONES = {
    "extreme": (OVERSOLD, OVERBOUGHT),
    "pullback": (PULLBACK_OVERSOLD, PULLBACK_OVERBOUGHT),
}


LONG = "long"
SHORT = "short"


@dataclass
class StrategySignal:
    """A single entry signal produced by the strategy."""

    direction: str  # LONG | SHORT
    entry_price: float  # close of the signal bar
    stop_loss: float
    target_price: float  # reward_risk * initial risk
    atr: float
    rsi: float
    time: str  # ISO timestamp of the signal bar ("" if unavailable)
    index: int  # positional bar index within the analysed DataFrame
    quality_score: float = 0.0  # 0-100 heuristic signal-quality score

    def to_dict(self) -> dict:
        return asdict(self)


def ema_series(closes: pd.Series, span: int) -> pd.Series:
    """Exponential moving average series (matches app-wide EMA convention)."""
    return closes.ewm(span=span, adjust=False).mean()


def rsi_series(closes: pd.Series, window: int = RSI_WINDOW) -> pd.Series:
    """Wilder RSI series (same algorithm as signal_engine.compute_rsi)."""
    delta = closes.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi = 100 - 100 / (1 + rs)
    # Pure-gain edge case: loss == 0 -> RSI 100; no data yet -> NaN stays.
    rsi = rsi.where(~((loss == 0) & (gain > 0)), 100.0)
    return rsi


def atr_series(df: pd.DataFrame, window: int = ATR_WINDOW) -> pd.Series:
    """Average True Range series (simple rolling mean of TR)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window).mean()


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with ema200/ema50/rsi/atr columns appended."""
    out = df.copy()
    closes = out["close"].astype(float)
    out["ema200"] = ema_series(closes, EMA_TREND_SPAN)
    out["ema50"] = ema_series(closes, EMA_FAST_SPAN)
    out["rsi"] = rsi_series(closes)
    out["atr"] = atr_series(out)
    return out


def _bar_time(df: pd.DataFrame, i: int) -> str:
    if "dts" in df.columns:
        value = df["dts"].iloc[i]
        try:
            return pd.Timestamp(value).isoformat()
        except (ValueError, TypeError):
            return str(value)
    try:
        return pd.Timestamp(df.index[i]).isoformat()
    except (ValueError, TypeError, IndexError):
        return ""


def _signal_quality(
    direction: str,
    close: float,
    ema200: float,
    ema50: float,
    rsi: float,
    rsi_prev: float,
    atr: float,
    open_price: float,
) -> float:
    """Heuristic 0-100 score for a candidate signal.

    Higher score when:
    - price is well displaced from EMA200 (strong trend),
    - EMA50 aligns with the trend,
    - RSI shows decisive momentum (large cross),
    - the signal candle has directional color.
    """
    if atr <= 0 or pd.isna(atr):
        return 0.0

    # Trend displacement from EMA200, normalised by ATR (capped).
    displacement = abs(close - ema200) / atr
    trend_score = min(displacement, 10.0) / 10.0 * 40.0

    # EMA50 alignment: full points if aligned, partial if close is on the
    # correct side, zero if wrong side.
    if direction == LONG:
        ema50_aligned = close > ema50
    else:
        ema50_aligned = close < ema50
    ema50_score = 20.0 if ema50_aligned else 0.0

    # RSI momentum: size of the cross through the threshold.
    rsi_momentum = abs(rsi - rsi_prev)
    rsi_score = min(rsi_momentum, 20.0) / 20.0 * 25.0

    # Candle color confirmation (price direction matches trade direction).
    if direction == LONG:
        color_ok = close > open_price
    else:
        color_ok = close < open_price
    color_score = 15.0 if color_ok else 0.0

    return min(trend_score + ema50_score + rsi_score + color_score, 100.0)


def detect_signals(
    df: pd.DataFrame,
    *,
    use_ema50: bool = False,
    require_candle_color: bool = False,
    atr_mult: float = 1.0,
    rsi_zone: str = "extreme",
    reward_risk: float = REWARD_RISK,
    min_quality_score: float = 0.0,
) -> list[StrategySignal]:
    """Scan ``df`` for entry signals.

    Long:  close > EMA200 and RSI crosses up through the configured zone.
    Short: close < EMA200 and RSI crosses down through the configured zone.

    ``rsi_zone``:
      - "extreme" (default, backward-compatible): 30/70 thresholds.
      - "pullback": 40/60 thresholds, generating more signals in strong
        trends where RSI rarely reaches the classical extremes.

    Optional filters: candle color (bullish/bearish close) and EMA50
    alignment. The first ``WARMUP_BARS`` bars never produce signals.
    """
    if len(df) <= WARMUP_BARS:
        return []

    data = enrich(df)
    signals: list[StrategySignal] = []

    oversold, overbought = RSI_ZONES.get(rsi_zone, RSI_ZONES["extreme"])
    min_quality_score = max(0.0, min(min_quality_score, 100.0))

    for i in range(WARMUP_BARS, len(data)):
        row = data.iloc[i]
        rsi_now = row["rsi"]
        rsi_prev = data["rsi"].iloc[i - 1]
        if pd.isna(rsi_now) or pd.isna(rsi_prev) or pd.isna(row["atr"]):
            continue

        close = float(row["close"])
        crossed_up = rsi_prev <= oversold < rsi_now
        crossed_down = rsi_prev >= overbought > rsi_now
        if not (crossed_up or crossed_down):
            continue

        if crossed_up and close > row["ema200"]:
            if use_ema50 and not close > row["ema50"]:
                continue
            if require_candle_color and not close > float(row["open"]):
                continue
            atr = float(row["atr"])
            stop = float(row["low"]) - atr_mult * atr
            risk = close - stop
            if risk <= 0:
                continue
            quality = _signal_quality(
                LONG,
                close,
                float(row["ema200"]),
                float(row["ema50"]),
                float(rsi_now),
                float(rsi_prev),
                atr,
                float(row["open"]),
            )
            signals.append(
                StrategySignal(
                    direction=LONG,
                    entry_price=close,
                    stop_loss=stop,
                    target_price=close + reward_risk * risk,
                    atr=atr,
                    rsi=float(rsi_now),
                    time=_bar_time(data, i),
                    index=i,
                    quality_score=quality,
                )
            )
        elif crossed_down and close < row["ema200"]:
            if use_ema50 and not close < row["ema50"]:
                continue
            if require_candle_color and not close < float(row["open"]):
                continue
            atr = float(row["atr"])
            stop = float(row["high"]) + atr_mult * atr
            risk = stop - close
            if risk <= 0:
                continue
            quality = _signal_quality(
                SHORT,
                close,
                float(row["ema200"]),
                float(row["ema50"]),
                float(rsi_now),
                float(rsi_prev),
                atr,
                float(row["open"]),
            )
            signals.append(
                StrategySignal(
                    direction=SHORT,
                    entry_price=close,
                    stop_loss=stop,
                    target_price=close - reward_risk * risk,
                    atr=atr,
                    rsi=float(rsi_now),
                    time=_bar_time(data, i),
                    index=i,
                    quality_score=quality,
                )
            )
    return [s for s in signals if s.quality_score >= min_quality_score]


def current_state(df: pd.DataFrame) -> dict | None:
    """Latest trend/momentum snapshot for the scan endpoint."""
    if len(df) <= WARMUP_BARS:
        return None
    data = enrich(df)
    row = data.iloc[-1]
    close = float(row["close"])
    ema200 = float(row["ema200"])
    atr = float(row["atr"]) if not pd.isna(row["atr"]) else None
    if close > ema200:
        trend = "bullish"
    elif close < ema200:
        trend = "bearish"
    else:
        trend = "neutral"
    deviation_pct = (close - ema200) / ema200 * 100 if ema200 else 0.0
    # EMA200 "entanglement" warning: price hugging the trend line.
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
