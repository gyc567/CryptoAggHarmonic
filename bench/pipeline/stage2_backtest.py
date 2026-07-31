"""Stage 2: Backtest wrapper around app/services/vibe/backtest_engine.

Runs the existing ``simulate_trades`` engine on a forward OHLCV window,
populates outcome / r_multiple / bars_held on the SignalRecord, then
calls ``apply_trade_metrics`` to fill in MAE / MFE / callback / stop
zone.

v3 changelog items 3, 4 + docs/HarmonicSignal-Bench.md Stage 2.

We deliberately do NOT modify ``app/services/vibe/backtest_engine.py``;
this wrapper treats it as a stable, well-tested black box.

Outcome label mapping (single-TP1 simulation):
  r_multiple > 0  → "tp1"        (15 marks in stage3)
  r_multiple == 0 → "breakeven"  ( 8 marks)
  r_multiple < 0  → "stoploss"   ( 0 marks)

The TP2/TP3 labels in stage3 are aspirational: to label "tp2"/"tp3",
re-run simulate_trades with the higher target and re-derive r. The
current wrapper keeps things simple and consistent with the engine's
single-target contract.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from app.services.vibe.backtest_engine import Trade, simulate_trades

from bench.dataset.signal_record import SignalRecord
from bench.pipeline.trade_metrics import apply_trade_metrics


def _row_position(df: pd.DataFrame, ts) -> Optional[int]:
    """Return positional row index for timestamp ``ts``; None if missing."""
    if ts is None:
        return None
    try:
        pos = df.index.get_loc(ts)
    except KeyError:
        return None
    if isinstance(pos, slice):
        return int(pos.start) if pos.start is not None else None
    return int(pos)


def stage2_backtest(
    rec: SignalRecord,
    forward_df: pd.DataFrame,
    tp1: Optional[float] = None,
) -> Optional[Trade]:
    """Run simulate_trades on ``forward_df`` and populate the record.

    Args:
      rec: signal record. Must have direction, entry_price, stop_price.
        Will read ``tp1`` from ``rec.tp1`` unless overridden.
      forward_df: OHLCV window starting at or after rec.timestamp with
        columns ['open','high','low','close','volume'].
      tp1: explicit TP1 price; defaults to ``rec.tp1``.

    Returns:
      The Trade produced by the engine, or None if the entry was never
      triggered within the window.

    Mutates ``rec`` with: outcome, r_multiple, bars_held, and the full
    trade-metrics field set via ``apply_trade_metrics``.
    """
    target = tp1 if tp1 is not None else rec.tp1
    if target is None:
        raise ValueError("rec.tp1 is None and no explicit tp1 provided")
    if rec.entry_price is None or rec.stop_price is None:
        raise ValueError("rec.entry_price / rec.stop_price must be set")
    # Backfill rec.tp1 so downstream trade_metrics can read it.
    if rec.tp1 is None:
        rec.tp1 = target

    trades = simulate_trades(
        df=forward_df,
        direction=rec.direction,
        entry_price=rec.entry_price,
        stop_loss=rec.stop_price,
        target_price=target,
    )

    if not trades:
        rec.outcome = None
        rec.r_multiple = None
        rec.bars_held = None
        return None

    trade = trades[0]

    if trade.r_multiple > 0:
        rec.outcome = "tp1"
    elif trade.r_multiple == 0:
        rec.outcome = "breakeven"
    else:
        rec.outcome = "stoploss"
    rec.r_multiple = trade.r_multiple

    entry_pos = _row_position(forward_df, trade.entry_time)
    exit_pos = _row_position(forward_df, trade.exit_time)
    # simulate_trades always sets entry_time and exit_time on returned trades,
    # and they are guaranteed to be present in forward_df (since the engine
    # ran against this exact df). So _row_position returning None here is a
    # bug — raise rather than silently fall back.
    if entry_pos is None or exit_pos is None or exit_pos < entry_pos:
        raise ValueError(
            f"could not resolve entry/exit positions: "
            f"entry_time={trade.entry_time}, exit_time={trade.exit_time}"
        )
    rec.bars_held = exit_pos - entry_pos + 1
    held_df = forward_df.iloc[entry_pos: exit_pos + 1]

    apply_trade_metrics(rec, held_df)
    return trade
