"""Event-driven backtest for the trend-RSI strategy (pure, no I/O).

Simulates each signal bar-by-bar with the strategy's exit discipline:

1. stop loss hit            -> close everything at the stop (-1R per unit)
2. target 1:2 hit           -> default: close everything (+2R);
                               ``partial_mode``: close 50% at target, move
                               stop to breakeven, let the rest run
3. RSI re-enters extreme    -> (partial_mode only) reduce half of the
                               remaining position at that bar's close
4. close flips across EMA200 -> trend environment changed, exit at close
5. end of data              -> close at the last close ("scratch" allowed)

Conservative same-bar rule: if a bar touches both stop and target, the
stop is assumed to be hit first.

R multiples are position-weighted: ``r(price)`` is the reward in units of
initial risk, and partial exits contribute ``fraction * r(price)``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

import pandas as pd

from app.domain.rsi_trend import (
    LONG,
    OVERBOUGHT,
    OVERSOLD,
    StrategySignal,
    _bar_time,
    enrich,
)

# Exit reasons
EXIT_STOP = "stop_loss"
EXIT_TARGET = "target"
EXIT_PARTIAL_TARGET = "partial_target"  # informational, recorded in partials
EXIT_RSI_EXTREME = "rsi_extreme"
EXIT_TREND_FLIP = "trend_flip"
EXIT_END = "end_of_data"


@dataclass
class PartialExit:
    fraction: float  # fraction of the ORIGINAL position
    price: float
    r_multiple: float  # fraction-weighted R contribution
    reason: str
    time: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StrategyTrade:
    direction: str
    entry_price: float
    entry_time: str
    stop_loss: float
    target_price: float
    exit_price: float
    exit_time: str
    exit_reason: str
    r_multiple: float
    bars_held: int
    partials: list[PartialExit] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        return data


@dataclass
class BacktestResult:
    total_signals: int
    trades_count: int
    win_count: int
    loss_count: int
    scratch_count: int
    win_rate: float
    avg_r: float
    total_r: float
    profit_factor: Optional[float]
    max_drawdown_r: float
    avg_bars_held: float
    trades: list[StrategyTrade]

    def to_dict(self) -> dict:
        return {
            "total_signals": self.total_signals,
            "trades_count": self.trades_count,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "scratch_count": self.scratch_count,
            "win_rate": self.win_rate,
            "avg_r": self.avg_r,
            "total_r": self.total_r,
            "profit_factor": self.profit_factor,
            "max_drawdown_r": self.max_drawdown_r,
            "avg_bars_held": self.avg_bars_held,
            "trades": [t.to_dict() for t in self.trades],
        }


def _r_multiple(direction: str, entry: float, initial_stop: float, price: float) -> float:
    risk = abs(entry - initial_stop)
    if risk <= 0:
        return 0.0
    if direction == LONG:
        return (price - entry) / risk
    return (entry - price) / risk


def _simulate_one(
    data: pd.DataFrame,
    signal: StrategySignal,
    *,
    partial_mode: bool,
    bar_time,
) -> StrategyTrade:
    """Simulate a single trade from its signal bar to its exit."""
    entry = signal.entry_price
    initial_stop = signal.stop_loss
    target = signal.target_price
    direction = signal.direction
    long = direction == LONG

    remaining = 1.0  # fraction of original position still open
    realized_r = 0.0
    stop = initial_stop
    t1_done = False
    rsi_done = False
    partials: list[PartialExit] = []

    exit_price = entry
    exit_time = signal.time
    exit_reason = EXIT_END
    exit_index = signal.index

    for i in range(signal.index, len(data)):
        row = data.iloc[i]
        high, low, close = float(row["high"]), float(row["low"]), float(row["close"])
        ema200 = row["ema200"]
        rsi = row["rsi"]
        time = bar_time(data, i)

        if i > signal.index:
            # 1) Stop loss (conservative: checked before target on same bar).
            stop_hit = low <= stop if long else high >= stop
            target_hit = high >= target if long else low <= target

            if stop_hit:
                exit_price, exit_reason = stop, EXIT_STOP
                realized_r += remaining * _r_multiple(direction, entry, initial_stop, stop)
                remaining = 0.0
                exit_index, exit_time = i, time
                break

            # 2) First target 1:2.
            if target_hit and not t1_done:
                if partial_mode:
                    half = remaining * 0.5
                    r = _r_multiple(direction, entry, initial_stop, target)
                    realized_r += half * r
                    partials.append(
                        PartialExit(half, target, half * r, EXIT_PARTIAL_TARGET, time)
                    )
                    remaining -= half
                    t1_done = True
                    stop = entry  # move to breakeven, let the rest run
                else:
                    exit_price, exit_reason = target, EXIT_TARGET
                    realized_r += remaining * _r_multiple(
                        direction, entry, initial_stop, target
                    )
                    remaining = 0.0
                    exit_index, exit_time = i, time
                    break

            # 3) RSI re-enters the extreme zone -> reduce half of the rest.
            if partial_mode and t1_done and not rsi_done and not pd.isna(rsi):
                extreme = rsi > OVERBOUGHT if long else rsi < OVERSOLD
                if extreme:
                    half = remaining * 0.5
                    r = _r_multiple(direction, entry, initial_stop, close)
                    realized_r += half * r
                    partials.append(
                        PartialExit(half, close, half * r, EXIT_RSI_EXTREME, time)
                    )
                    remaining -= half
                    rsi_done = True

            # 4) Trend environment flipped across EMA200 -> exit at close.
            if not pd.isna(ema200):
                flipped = close < ema200 if long else close > ema200
                if flipped:
                    exit_price, exit_reason = close, EXIT_TREND_FLIP
                    realized_r += remaining * _r_multiple(
                        direction, entry, initial_stop, close
                    )
                    remaining = 0.0
                    exit_index, exit_time = i, time
                    break
        else:
            # Signal bar itself: only an immediate same-bar stop is honoured
            # (entry at close, so only the close can take us out).
            stop_hit = low <= stop if long else high >= stop
            if stop_hit:
                exit_price, exit_reason = stop, EXIT_STOP
                realized_r += remaining * _r_multiple(direction, entry, initial_stop, stop)
                remaining = 0.0
                exit_index, exit_time = i, time
                break

    if remaining > 0:
        # Ran out of data: flatten at the last close.
        last = data.iloc[-1]
        exit_price = float(last["close"])
        exit_reason = EXIT_END
        exit_index = len(data) - 1
        exit_time = bar_time(data, exit_index)
        realized_r += remaining * _r_multiple(direction, entry, initial_stop, exit_price)

    return StrategyTrade(
        direction=direction,
        entry_price=entry,
        entry_time=signal.time,
        stop_loss=initial_stop,
        target_price=target,
        exit_price=exit_price,
        exit_time=exit_time,
        exit_reason=exit_reason,
        r_multiple=realized_r,
        bars_held=exit_index - signal.index,
        partials=partials,
    )


def run_backtest(
    df: pd.DataFrame,
    signals: list[StrategySignal],
    *,
    partial_mode: bool = False,
) -> BacktestResult:
    """Simulate all signals over ``df`` and aggregate performance metrics.

    Only one position may be open at a time; signals that fire while a
    trade is still open are skipped.
    """
    data = enrich(df)

    trades: list[StrategyTrade] = []
    open_until = -1  # last bar index covered by an open trade
    for signal in signals:
        if signal.index <= open_until:
            continue
        trade = _simulate_one(data, signal, partial_mode=partial_mode, bar_time=_bar_time)
        trades.append(trade)
        open_until = signal.index + trade.bars_held

    wins = [t for t in trades if t.r_multiple > 0]
    losses = [t for t in trades if t.r_multiple < 0]
    scratches = [t for t in trades if t.r_multiple == 0]
    total_r = sum(t.r_multiple for t in trades)
    gross_win = sum(t.r_multiple for t in wins)
    gross_loss = abs(sum(t.r_multiple for t in losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (
        None if gross_win == 0 else float("inf")
    )

    # Max drawdown on the cumulative-R equity curve (trade close order).
    peak = 0.0
    max_dd = 0.0
    cumulative = 0.0
    for t in trades:
        cumulative += t.r_multiple
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)

    n = len(trades)
    return BacktestResult(
        total_signals=len(signals),
        trades_count=n,
        win_count=len(wins),
        loss_count=len(losses),
        scratch_count=len(scratches),
        win_rate=(len(wins) / n) if n else 0.0,
        avg_r=(total_r / n) if n else 0.0,
        total_r=total_r,
        profit_factor=profit_factor,
        max_drawdown_r=max_dd,
        avg_bars_held=(sum(t.bars_held for t in trades) / n) if n else 0.0,
        trades=trades,
    )
