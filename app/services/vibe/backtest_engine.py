"""Simplified event-driven backtest engine for vibe trading signals.

The engine walks a historical OHLCV DataFrame and simulates trades based on a
fixed direction, entry price, stop loss and target price.

Fidelity model (audit T7):
  - Fees:        optional ``fee_bps`` on each side (round-trip deducted from R).
  - Slippage:    optional ``slippage_bps`` applied as adverse price move on
                 entry and exit. The backtest "acts" pessimistically.
  - Funding:     optional ``funding_bps_per_8h`` for perpetual futures. Drawn
                 down once per 8-hour bar the position is open.
  - Leverage:    optional integer multiplier. R-multiple is reported in
                 notional terms so leverage is reflected, but liquidation is
                 not modelled (the audit flagged this — flagged here as a known
                 limitation and not silently ignored).

Items NOT modelled (kept honest rather than silently dropped):
  - Partial fills (single-fill assumption).
  - Liquidation / maintenance margin.
  - Order book depth / impact.
The caller is responsible for sanity-checking any hyperopt/optimisation that
depends on these knobs being absent.
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
    # Audit T7: track fee + slippage + funding contributions for transparency.
    fees_paid: float = 0.0
    slippage_paid: float = 0.0
    funding_paid: float = 0.0
    notional_risk: float = 0.0  # per-unit risk in price terms (entry - stop)


@dataclass
class BacktestConfig:
    """Realism knobs for the backtest engine.

    Audit T7: every knob is OPT-IN by default (0.0 / 1) so legacy callers
    that pass no config get the previous "perfect fills" behaviour. To get
    Binance USDⓈ-M-futures-style realism, pass:

        BacktestConfig(
            fee_bps=4.0,             # 0.04% per side
            slippage_bps=2.0,        # 0.02% per fill
            funding_bps_per_8h=1.0,  # typical neutral
            leverage=3,
            bar_hours=1.0,
        )

    Set any individual value to 0 to disable that model. Set ``leverage``
    to 1 (default) for spot / no-margin amplification.
    """

    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    funding_bps_per_8h: float = 0.0
    leverage: int = 1
    bar_hours: float = 1.0  # candle size in hours; drives funding cadence


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
    # Audit T7: surface the realism knobs actually used so reports aren't
    # accidentally comparing apples to oranges.
    config_used: Optional[BacktestConfig] = None
    total_fees: float = 0.0
    total_slippage: float = 0.0
    total_funding: float = 0.0
    # Audit T8: low-sample guardrail. Callers (promotion gates) MUST treat
    # is_low_sample == True as a hard block — Sharpe on 5 trades is noise.
    is_low_sample: bool = False
    min_trades_required: int = 30


def simulate_trades(
    df: pd.DataFrame,
    direction: Literal["long", "short"],
    entry_price: float,
    stop_loss: float,
    target_price: float,
    config: Optional[BacktestConfig] = None,
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

    Audit T7: ``config`` controls fees, slippage, funding, and leverage. Each
    fill's effective price is shifted adversely by slippage, and the R-multiple
    is debited by per-trade fees + per-bar funding. ``Trade`` records the
    individual contributions so callers can audit them.
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

    cfg = config or BacktestConfig()
    if cfg.leverage is None or cfg.leverage < 1:
        raise ValueError("leverage must be a positive integer")
    slip = cfg.slippage_bps / 10_000.0
    fee = cfg.fee_bps / 10_000.0
    funding_rate = cfg.funding_bps_per_8h / 10_000.0
    funding_per_bar = funding_rate * (cfg.bar_hours / 8.0)

    # Apply slippage pessimistically — broker always fills the worse side.
    # Long:  entry +slip (paid more), stop -slip (cut earlier), target -slip (received less)
    # Short: entry -slip (received less), stop +slip (cut earlier), target +slip (paid more)
    eff_entry = entry_price * (1 + slip) if direction == "long" else entry_price * (1 - slip)
    eff_stop = stop_loss * (1 - slip) if direction == "long" else stop_loss * (1 + slip)
    eff_target = target_price * (1 - slip) if direction == "long" else target_price * (1 + slip)

    trades: list[Trade] = []
    in_trade = False
    trade: Optional[Trade] = None
    last_timestamp: pd.Timestamp | None = None
    last_close = 0.0
    bars_in_trade = 0

    def _close_trade(t: Trade, exit_price: float, result: Literal["win", "loss"], exit_time: pd.Timestamp) -> None:
        t.exit_price = exit_price
        t.result = result
        t.exit_time = exit_time
        # Funding is paid once per bar held. Per-unit notional is exit_price.
        t.funding_paid = funding_per_bar * bars_in_trade * exit_price
        # Fees are round-trip (entry + exit) on notional.
        t.fees_paid = fee * (t.entry_price + exit_price)
        # Slippage was already baked into the entry/exit prices.
        t.slippage_paid = 0.0
        risk = abs(t.entry_price - t.stop_loss)
        t.notional_risk = risk
        reward = abs(exit_price - t.entry_price)
        if risk <= 0:
            t.r_multiple = 0.0
            return
        gross_r = reward / risk
        # Subtract fees (relative to risk) and funding (relative to risk).
        drag = (t.fees_paid + t.funding_paid) / risk
        net_r = gross_r - drag
        t.r_multiple = -abs(net_r) if result == "loss" else net_r

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
                bars_in_trade = 0
                trade = Trade(
                    direction=direction,
                    entry_price=eff_entry,
                    stop_loss=eff_stop,
                    target_price=eff_target,
                    exit_price=0.0,
                    result="scratch",
                    entry_time=timestamp,
                )
                # Fast markets may stop/target out on the same candle.
                exit_price, result = _resolve_exit(
                    direction=direction,
                    low=low,
                    high=high,
                    entry_price=eff_entry,
                    stop_loss=eff_stop,
                    target_price=eff_target,
                )
                if result is not None and trade is not None:
                    _close_trade(trade, exit_price, result, timestamp)
                    trades.append(trade)
                    in_trade = False
                    trade = None
                else:
                    bars_in_trade += 1
            continue

        bars_in_trade += 1
        # We are in a trade: determine which level was hit first.
        exit_price, result = _resolve_exit(
            direction=direction,
            low=low,
            high=high,
            entry_price=eff_entry,
            stop_loss=eff_stop,
            target_price=eff_target,
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
        trade.funding_paid = funding_per_bar * bars_in_trade * last_close
        trade.fees_paid = fee * (trade.entry_price + last_close)
        trade.notional_risk = abs(trade.entry_price - trade.stop_loss)
        if trade.notional_risk > 0:
            trade.r_multiple = 0.0 - (trade.fees_paid + trade.funding_paid) / trade.notional_risk
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


def compute_metrics(
    trades: list[Trade],
    config: Optional[BacktestConfig] = None,
    min_trades: int = 30,
) -> BacktestSummary:
    """Compute summary metrics from a list of simulated trades.

    ``config`` is echoed into the summary so downstream reports can show
    which realism knobs were applied (audit T7 — don't compare apples to
    oranges).

    ``min_trades`` (default 30) is a guardrail against overfit / statistical
    noise (audit T8). When ``len(trades) < min_trades``, ``summary.is_low_sample``
    is True so callers can refuse to act on the metrics (e.g. block
    promotion gates in app/loop/tuning_promotion_v3.py).
    """
    summary = BacktestSummary(trades=trades, config_used=config)
    summary.is_low_sample = len(trades) < min_trades  # type: ignore[attr-defined]
    summary.min_trades_required = min_trades  # type: ignore[attr-defined]
    if not trades:
        return summary

    summary.total_signals = len(trades)
    summary.win_count = sum(1 for t in trades if t.result == "win")
    summary.loss_count = sum(1 for t in trades if t.result == "loss")
    summary.scratch_count = sum(1 for t in trades if t.result == "scratch")
    summary.win_rate = summary.win_count / summary.total_signals
    summary.avg_rr = sum(t.r_multiple for t in trades) / summary.total_signals
    summary.total_r = sum(t.r_multiple for t in trades)
    summary.total_fees = sum(t.fees_paid for t in trades)
    summary.total_slippage = sum(t.slippage_paid for t in trades)
    summary.total_funding = sum(t.funding_paid for t in trades)

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
