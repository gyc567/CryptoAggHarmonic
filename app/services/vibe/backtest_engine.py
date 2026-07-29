"""Simplified event-driven backtest engine for vibe trading signals.

The engine walks a historical OHLCV DataFrame and simulates trades based on a
fixed direction, entry price, stop loss and target price. It is intentionally
simplified: it does not model slippage, fees, partial fills, position sizing,
or time-in-force.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd


@dataclass
class Trade:
    """A single simulated trade outcome."""

    direction: Literal["long", "short"]
    entry_price: float
    stop_loss: float
    target_price: float
    exit_price: float
    result: Literal["win", "loss", "scratch"]
    r_multiple: float = 0.0
    entry_time: pd.Timestamp | None = None
    exit_time: pd.Timestamp | None = None


@dataclass
class BacktestSummary:
    """Summary metrics produced by the backtest engine."""

    total_signals: int = 0
    win_count: int = 0
    loss_count: int = 0
    scratch_count: int = 0
    win_rate: float = 0.0
    avg_rr: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    total_r: float = 0.0
    trades: list[Trade] = field(default_factory=list)


def simulate_trades(
    df: pd.DataFrame,
    direction: Literal["long", "short"],
    entry_price: float,
    stop_loss: float,
    target_price: float,
) -> list[Trade]:
    """Walk historical candles and simulate each time price touches entry.

    Rules:
      - A trade is entered on a candle whose range straddles ``entry_price``.
      - The entry candle itself is checked for stop/target touches, so fast
        moves that trigger entry and immediately hit a level are not ignored.
      - If both stop and target are within the same candle's range, the one
        closer to the entry price is assumed to trigger first (conservative
        simplification). When distances are equal, the stop is assumed first.
      - Stop and target must be on the correct side of entry for the direction;
        otherwise the input is rejected.
      - Any trade still open at the end of the series is closed at the last
        close price and counted as a scratch (0 R).
    """
    if df.empty:
        return []

    required = {"open", "high", "low", "close"}
    if not required.issubset(set(df.columns)):
        raise ValueError(f"DataFrame must contain columns {required}")

    if direction == "long":
        if stop_loss >= entry_price or target_price <= entry_price:
            raise ValueError("Long trade requires stop < entry < target")
    else:
        if stop_loss <= entry_price or target_price >= entry_price:
            raise ValueError("Short trade requires stop > entry > target")

    trades: list[Trade] = []
    in_trade = False
    trade: Optional[Trade] = None
    last_timestamp: pd.Timestamp | None = None
    last_close = 0.0

    def _close_trade(t: Trade, exit_price: float, result: Literal["win", "loss"], exit_time: pd.Timestamp) -> None:
        t.exit_price = exit_price
        t.result = result
        t.exit_time = exit_time
        risk = abs(entry_price - stop_loss)
        reward = abs(exit_price - entry_price)
        t.r_multiple = reward / risk if risk > 0 else 0.0
        if result == "loss":
            t.r_multiple = -abs(t.r_multiple)

    for timestamp, row in df.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        last_timestamp = timestamp
        last_close = float(row["close"])

        if not in_trade:
            # Check whether price touched the entry level this candle.
            entry_triggered = low <= entry_price <= high if direction == "long" else high >= entry_price >= low
            if entry_triggered:
                in_trade = True
                trade = Trade(
                    direction=direction,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    target_price=target_price,
                    exit_price=0.0,
                    result="scratch",
                    entry_time=timestamp,
                )
                # Fast markets may stop/target out on the same candle.
                exit_price, result = _resolve_exit(
                    direction=direction,
                    low=low,
                    high=high,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    target_price=target_price,
                )
                if result is not None and trade is not None:
                    _close_trade(trade, exit_price, result, timestamp)
                    trades.append(trade)
                    in_trade = False
                    trade = None
            continue

        # We are in a trade: determine which level was hit first.
        exit_price, result = _resolve_exit(
            direction=direction,
            low=low,
            high=high,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
        )
        if result is not None and trade is not None:
            _close_trade(trade, exit_price, result, timestamp)
            trades.append(trade)
            in_trade = False
            trade = None

    # Close any trade still open at the end of the data as a scratch.
    if in_trade and trade is not None and last_timestamp is not None:
        trade.exit_price = last_close
        trade.result = "scratch"
        trade.exit_time = last_timestamp
        trade.r_multiple = 0.0
        trades.append(trade)

    return trades


def _resolve_exit(
    direction: Literal["long", "short"],
    low: float,
    high: float,
    entry_price: float,
    stop_loss: float,
    target_price: float,
) -> tuple[float, Literal["win", "loss"] | None]:
    """Return the assumed exit price and result for one candle.

    If neither level is touched, returns (0.0, None). If both are touched,
    the level closer to the entry price is chosen; if exactly equidistant,
    the stop (loss) is chosen as the conservative assumption.
    """
    if direction == "long":
        stop_hit = low <= stop_loss
        target_hit = high >= target_price
        if not stop_hit and not target_hit:
            return 0.0, None
        if stop_hit and target_hit:
            # Pick the closer level as the first touch.
            if (entry_price - stop_loss) <= (target_price - entry_price):
                return stop_loss, "loss"
            return target_price, "win"
        if stop_hit:
            return stop_loss, "loss"
        return target_price, "win"

    # short
    stop_hit = high >= stop_loss
    target_hit = low <= target_price
    if not stop_hit and not target_hit:
        return 0.0, None
    if stop_hit and target_hit:
        if (stop_loss - entry_price) <= (entry_price - target_price):
            return stop_loss, "loss"
        return target_price, "win"
    if stop_hit:
        return stop_loss, "loss"
    return target_price, "win"


def compute_metrics(trades: list[Trade]) -> BacktestSummary:
    """Compute summary metrics from a list of simulated trades."""
    summary = BacktestSummary(trades=trades)
    if not trades:
        return summary

    summary.total_signals = len(trades)
    summary.win_count = sum(1 for t in trades if t.result == "win")
    summary.loss_count = sum(1 for t in trades if t.result == "loss")
    summary.scratch_count = sum(1 for t in trades if t.result == "scratch")
    summary.win_rate = summary.win_count / summary.total_signals
    summary.avg_rr = sum(t.r_multiple for t in trades) / summary.total_signals
    summary.total_r = sum(t.r_multiple for t in trades)

    wins = [t.r_multiple for t in trades if t.result == "win"]
    losses = [abs(t.r_multiple) for t in trades if t.result == "loss"]
    summary.profit_factor = sum(wins) / sum(losses) if losses else float("inf")

    # Running equity curve in R multiples to compute max drawdown.
    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    for t in trades:
        equity += t.r_multiple
        peak = max(peak, equity)
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    summary.max_drawdown = max_dd

    return summary
