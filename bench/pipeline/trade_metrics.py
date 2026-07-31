"""Trade metrics — MAE/MFE/callback/stop-zone computation.

v3 changelog items 3, 4 + docs/HarmonicSignal-Bench.md trade_metrics.

Pure functions. Inputs are OHLCV DataFrames + SignalRecord; outputs
are dicts that the caller writes back onto the record.

Long direction:
  run_pnl_per_bar = (low - entry) / (stop - entry)         [negative = loss]
  MAE = abs(min(run_pnl_per_bar, 0)) * stop_distance
  MFE = max(high - entry, 0)
  callback_depth = max(entry - low, 0) / atr_at_entry      [unit ATR]
  closest_to_stop = max(entry - low, 0)
  buffer_consumption = closest_to_stop / (entry - stop)

Short direction (signs reversed):
  run_pnl_per_bar = (entry - high) / (entry - stop)
  MAE = abs(min(run_pnl_per_bar, 0)) * stop_distance
  MFE = max(entry - low, 0)
  callback_depth = max(high - entry, 0) / atr_at_entry
  closest_to_stop = max(high - entry, 0)
  buffer_consumption = closest_to_stop / (stop - entry)
"""

from __future__ import annotations

from typing import Literal, Optional, TypedDict

import pandas as pd

Direction = Literal["long", "short"]


class TradeMetrics(TypedDict, total=False):
    mae: float
    mfe: float
    mae_atr_ratio: float
    mfe_atr_ratio: float
    callback_depth: float
    callback_bars: int
    callback_volume_ratio: Optional[float]
    hit_stop_before_tp: bool
    stop_zone_touches: int
    price_efficiency: float


def compute_trade_metrics(
    df: pd.DataFrame,
    entry_price: float,
    stop_price: float,
    target_price: float,
    direction: Direction,
    atr_at_entry: float,
    stop_zone_atr: float = 0.1,
) -> TradeMetrics:
    """Walk the forward OHLCV and compute MAE/MFE/callback/stop-zone.

    The caller (stage2_backtest) determines the exit bar (TP hit, stop
    hit, or scratch) and passes only the bars the trade was actually
    held. We don't infer exit here.

    Args:
      df: forward-window DataFrame with at least ``['open','high','low',
        'close','volume']`` columns.
      entry_price: actual entry price used by the trade.
      stop_price: stop level.
      target_price: target level (TP1).
      direction: 'long' or 'short'.
      atr_at_entry: ATR at entry, for unit conversion.
      stop_zone_atr: half-width of the stop zone in ATR (default 0.1).

    Returns:
      TradeMetrics dict. Missing fields = not computable from inputs.
    """
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing columns: {sorted(missing)}")
    if df.empty:
        raise ValueError("DataFrame is empty")
    if entry_price <= 0 or stop_price <= 0 or target_price <= 0:
        raise ValueError("prices must be positive")
    if atr_at_entry <= 0:
        raise ValueError("atr_at_entry must be positive")
    if stop_zone_atr < 0:
        raise ValueError("stop_zone_atr must be non-negative")

    if direction == "long":
        if not (stop_price < entry_price < target_price):
            raise ValueError("Long requires stop < entry < target")
    else:
        if not (stop_price > entry_price > target_price):
            raise ValueError("Short requires stop > entry > target")

    risk_distance = abs(entry_price - stop_price)
    # Note: invariant checks above guarantee risk_distance > 0; no need
    # to recheck.

    # MAE in price distance (absolute), MFE in price distance (absolute)
    mae_price = 0.0
    mfe_price = 0.0
    mae_bar_index: Optional[int] = None
    stop_zone_touches = 0
    hit_stop = False
    hit_target = False

    stop_zone_low, stop_zone_high = _stop_zone(
        stop_price, atr_at_entry, stop_zone_atr, direction
    )

    for i, (_, row) in enumerate(df.iterrows()):
        bar_high = float(row["high"])
        bar_low = float(row["low"])

        if direction == "long":
            bar_mae = max(entry_price - bar_low, 0.0)
            bar_mfe = max(bar_high - entry_price, 0.0)
            stop_hit = bar_low <= stop_price
            target_hit = bar_high >= target_price
            in_stop_zone = bar_low <= stop_zone_high and bar_high >= stop_zone_low
        else:  # short
            bar_mae = max(bar_high - entry_price, 0.0)
            bar_mfe = max(entry_price - bar_low, 0.0)
            stop_hit = bar_high >= stop_price
            target_hit = bar_low <= target_price
            in_stop_zone = bar_high >= stop_zone_low and bar_low <= stop_zone_high

        if bar_mae > mae_price:
            mae_price = bar_mae
            mae_bar_index = i
        if bar_mfe > mfe_price:
            mfe_price = bar_mfe

        if in_stop_zone:
            stop_zone_touches += 1

        if stop_hit and not hit_target:
            hit_stop = True
        if target_hit:
            hit_target = True

    mae_atr_ratio = mae_price / atr_at_entry
    mfe_atr_ratio = mfe_price / atr_at_entry
    callback_depth_atr = mae_atr_ratio  # MAE / ATR is the depth in ATR units

    # callback_volume_ratio: mean volume in MAE segment / mean volume before MAE
    callback_volume_ratio = _callback_volume_ratio(
        df, mae_bar_index, n_pre=20
    )

    # callback_bars: how many bars until MAE
    callback_bars = (mae_bar_index + 1) if mae_bar_index is not None else 0

    return TradeMetrics(
        mae=mae_price,
        mfe=mfe_price,
        mae_atr_ratio=mae_atr_ratio,
        mfe_atr_ratio=mfe_atr_ratio,
        callback_depth=callback_depth_atr,
        callback_bars=callback_bars,
        callback_volume_ratio=callback_volume_ratio,
        hit_stop_before_tp=hit_stop and not hit_target,
        stop_zone_touches=stop_zone_touches,
        # price_efficiency is set by apply_trade_metrics below based on
        # outcome; this function cannot determine it.
    )


def _stop_zone(
    stop_price: float,
    atr: float,
    zone_atr: float,
    direction: Direction,
) -> tuple[float, float]:
    """Return the (low, high) of the stop zone."""
    half = atr * zone_atr
    return stop_price - half, stop_price + half


def _callback_volume_ratio(
    df: pd.DataFrame, mae_bar_index: Optional[int], n_pre: int = 20
) -> Optional[float]:
    """Return mean volume in [0..mae_bar_index] / mean volume in pre-MAE window.

    If ``mae_bar_index`` is None (no MAE observed), return None.
    If the pre-MAE window is empty, return None.
    """
    if mae_bar_index is None:
        return None
    if mae_bar_index <= 0:
        # MAE happened on bar 0; no pre-window
        return None
    pre = df.iloc[:mae_bar_index]["volume"]
    callback = df.iloc[: mae_bar_index + 1]["volume"]
    pre_mean = float(pre.mean())
    if pre_mean <= 0:
        return None
    return float(callback.mean()) / pre_mean


def price_efficiency_for(
    outcome: str,
    tp_bar_index: Optional[int],
    total_bars_held: int,
) -> float:
    """Return 0-1 efficiency per v3 changelog item 5.

    Per v3 changelog: TP hit → tp_bar / total_bars; non-TP exit → 0.
    Note: we use 0 (not 1) for stopped exits; the previous "floor 1"
    was a v0.1 placeholder and the spec is explicit.
    """
    if outcome in ("tp3", "tp2", "tp1"):
        if tp_bar_index is None or total_bars_held <= 0:
            return 0.0
        eff = tp_bar_index / total_bars_held
        if eff > 1.0:
            return 1.0
        return eff
    return 0.0


def find_tp_bar(
    df: pd.DataFrame,
    direction: Direction,
    target_price: float,
) -> Optional[int]:
    """Return the bar index of the first TP touch, or None.

    Index is positional within ``df`` (0-based). The trade must
    already have entered — typically the runner passes bars starting
    at the bar AFTER entry.
    """
    if df.empty:
        return None
    for i, (_, row) in enumerate(df.iterrows()):
        bar_high = float(row["high"])
        bar_low = float(row["low"])
        if direction == "long" and bar_high >= target_price:
            return i
        if direction == "short" and bar_low <= target_price:
            return i
    return None


def apply_trade_metrics(rec, df: pd.DataFrame) -> None:
    """Compute trade metrics for one record and write back.

    Convenience wrapper: reads price fields off ``rec``, calls
    ``compute_trade_metrics``, writes MAE/MFE/callback/etc. back onto
    the record. ``rec.outcome`` and ``rec.bars_held`` are used to set
    ``price_efficiency`` via ``price_efficiency_for``.
    """
    m = compute_trade_metrics(
        df=df,
        entry_price=rec.entry_price,
        stop_price=rec.stop_price,
        target_price=rec.tp1,
        direction=rec.direction,
        atr_at_entry=rec.atr_at_entry,
    )
    for k, v in m.items():
        if v is None:
            continue
        # only set attributes the record actually has
        if hasattr(rec, k):
            setattr(rec, k, v)

    # price_efficiency
    if rec.outcome is not None and rec.bars_held is not None and rec.bars_held > 0:
        tp_bar = find_tp_bar(df, rec.direction, rec.tp1)
        rec.price_efficiency = price_efficiency_for(
            rec.outcome, tp_bar, rec.bars_held
        )
    else:
        rec.price_efficiency = None
