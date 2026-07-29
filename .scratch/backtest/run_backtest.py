"""Walk-forward backtest harness for the v2 harmonic pattern engine.

Three groups compared:
- control: stock signal_engine (no v2 filters, no macro)
- strict:  + discipline filters (path-integrity, TTL, TP2 cross)
- experimental: + macro size_mult (regime-aware position sizing)

Simulation: for each detected formed XABCD pattern, generate a Signal via
``signal_engine.build_signal``. Walk forward bar-by-bar until exit:

1. stop hit  -> -1R
2. TP1 hit   -> +1R (or partial, default close-all)
3. TP2 hit   -> +2R or fractional based on remaining
4. max_hold  -> close at last close ("scratch")

Output: aggregated metrics per group, JSON written to .scratch/backtest/results/
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Optional

import pandas as pd

# Make the repo root importable.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.domain.signals import Candidate
from app.services.signal_engine import build_signal, extract_candidates
from app.services.discipline_filters import evaluate as discipline_evaluate
from app.services.macro_bias import compute as macro_compute


# --- Data loading -------------------------------------------------------------


def load_4h(csv_path: str) -> pd.DataFrame:
    """Load 1h CSV and resample to 4h."""
    df = pd.read_csv(csv_path)
    df["dts"] = pd.to_datetime(df["open_time"], unit="s", utc=True)
    df = df.rename(columns={"open_time": "close_time"})
    df = df[["open", "high", "low", "close", "volume", "close_time", "dts"]]
    df4 = (
        df.set_index("dts")
        .resample("4h")
        .agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        })
        .dropna()
        .reset_index()
    )
    df4["close_time"] = df4["dts"].astype("int64") // 10**9
    return df4


def to_daily_close(df4: pd.DataFrame) -> pd.Series:
    """Resample 4h closes to 1d for the macro_bias overlay."""
    return (
        df4.set_index("dts")["close"]
        .resample("1d")
        .last()
        .dropna()
    )


# --- Detector (loose config to surface real patterns) ------------------------


def detect_4h(df: pd.DataFrame, symbol: str, anchor_idx: int, window: int = 600,
               limit_to: int = 5):
    """Run pyharmonics detector on a trailing window ending at anchor_idx.

    Returns (candle_data, list[Candidate]) for formed patterns only.
    """
    from pyharmonics.technicals import OHLCTechnicals
    from pyharmonics.search import HarmonicSearch

    # Slice to the anchor window. Reset the index to 0..N-1 so pyharmonics
    # returns pattern.x as sub-df positions; we then look up close_times from
    # the sub df in extract_candidates.
    start = max(0, anchor_idx - window + 1)
    sub = df.iloc[start:anchor_idx + 1].reset_index(drop=True).copy()
    if len(sub) < 200:
        return None, []
    candle = SimpleNamespace(df=sub, symbol=symbol, interval="4h")
    try:
        t = OHLCTechnicals(
            candle.df, candle.symbol, candle.interval, peak_spacing=5,
        )
        hs = HarmonicSearch(t, fib_tolerance=0.05)
        hs.forming(limit_to=limit_to, percent_c_to_d=0.85)
        hs.search(limit_to=limit_to)
        # Extract as Candidate objects via the signal_engine adapter.
        det = {
            "raw_assessment": {
                "forming": hs.get_patterns(formed=False),
                "patterns": hs.get_patterns(),
            },
            "position": None,
        }
        cands = extract_candidates(det, sub["close_time"])
        # Keep only formed + XABCD (the family the engine grades).
        formed = [c for c in cands if c.formed and c.family == "XABCD"]
        return candle, formed
    except Exception as e:
        print(f"  detect error at {anchor_idx}: {e}")
        return None, []


def find_fresh_patterns(
    df: pd.DataFrame, symbol: str, anchor_step: int = 20,
    max_age_bars: int = 5, limit_to: int = 20,
) -> list[tuple[int, "Candidate"]]:
    """Walk forward through ``df`` and return every (anchor_idx, Candidate)
    where a freshly-completed XABCD pattern exists at the anchor.

    A pattern is "fresh" when its D point is within ``max_age_bars`` of the
    last bar in the slice we feed to pyharmonics. We step the anchor every
    ``anchor_step`` bars so the detector cost stays bounded.

    Returns:
        list of (anchor_idx, candidate) — anchor_idx is the position in the
        ORIGINAL df of the slice's last bar, candidate.times[-1] is in epoch
        seconds and consistent with the slice's close_time column.
    """
    from pyharmonics.technicals import OHLCTechnicals
    from pyharmonics.search import HarmonicSearch

    found: list[tuple[int, Candidate]] = []
    for anchor in range(200, len(df) - 50, anchor_step):
        sub = df.iloc[: anchor + 1].reset_index(drop=True).copy()
        if len(sub) < 200:
            continue
        try:
            c = SimpleNamespace(df=sub, symbol=symbol, interval="4h")
            t = OHLCTechnicals(c.df, c.symbol, c.interval, peak_spacing=5)
            hs = HarmonicSearch(t, fib_tolerance=0.05)
            hs.search(limit_to=limit_to)
            det = {
                "raw_assessment": {
                    "forming": hs.get_patterns(formed=False),
                    "patterns": hs.get_patterns(),
                },
                "position": None,
            }
            cands = extract_candidates(det, sub["close_time"])
        except Exception:
            continue
        last_sub_idx = len(sub) - 1
        for cand in cands:
            if not cand.formed or cand.family != "XABCD":
                continue
            if not cand.times:
                continue
            # cand.times are now epoch seconds; compare to the slice's last
            # bar's close_time to determine D-point freshness.
            d_time = cand.times[-1]
            last_close_time = sub["close_time"].iloc[last_sub_idx]
            # bars since D (4h granularity)
            age_sec = last_close_time - d_time
            age_bars = age_sec / 14400.0
            if age_bars <= max_age_bars:
                found.append((anchor, cand))
    return found


# --- Trade simulator ----------------------------------------------------------


@dataclass
class Trade:
    symbol: str
    pattern: str
    family: str
    direction: str
    entry_bar: int
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float
    exit_bar: int
    exit_price: float
    exit_reason: str
    r_multiple: float
    bars_held: int
    grade: str
    width_pct: float
    macro_size_mult: float = 1.0
    discipline_passed: bool = True
    group: str = ""


def _simulate_trade(
    df: pd.DataFrame, entry_bar: int, signal, max_hold_bars: int = 100,
) -> Trade:
    """Simulate one trade from entry_bar forward.

    Conservative same-bar rule: if both stop and target are touched on the
    same bar, stop is assumed to hit first.
    """
    direction = signal.direction
    long = (direction == "long")
    entry = signal.entry_reference
    stop = signal.stop_loss
    tp1 = signal.targets[0].price if signal.targets else None
    tp2 = signal.targets[1].price if len(signal.targets) > 1 else tp1

    end_bar = min(entry_bar + max_hold_bars, len(df) - 1)
    exit_bar = end_bar
    exit_price = float(df["close"].iloc[end_bar])
    exit_reason = "end_of_data"
    r = 0.0

    risk = abs(entry - stop)
    if risk <= 0:
        # degenerate, return scratch
        return Trade(
            symbol=df.attrs.get("symbol", ""),
            pattern=signal.pattern_name, family=signal.family,
            direction=direction, entry_bar=entry_bar, entry_price=entry,
            stop_loss=stop, tp1=tp1, tp2=tp2,
            exit_bar=entry_bar, exit_price=entry,
            exit_reason="degenerate_risk", r_multiple=0.0, bars_held=0,
            grade=signal.grade, width_pct=signal.width_pct or 0.0,
        )

    for i in range(entry_bar + 1, end_bar + 1):
        row = df.iloc[i]
        high, low = float(row["high"]), float(row["low"])
        stop_hit = (low <= stop) if long else (high >= stop)
        # Conservative: if stop hit, exit immediately at stop.
        if stop_hit:
            exit_bar = i
            exit_price = stop
            exit_reason = "stop_loss"
            r = -1.0
            break
        if tp1 is not None:
            tp1_hit = (high >= tp1) if long else (low <= tp1)
            if tp1_hit:
                # Close full at TP1 (default policy; no partials for the backtest).
                exit_bar = i
                exit_price = tp1
                exit_reason = "tp1"
                r = (tp1 - entry) / risk if long else (entry - tp1) / risk
                break
        if tp2 is not None:
            tp2_hit = (high >= tp2) if long else (low <= tp2)
            if tp2_hit:
                exit_bar = i
                exit_price = tp2
                exit_reason = "tp2"
                r = (tp2 - entry) / risk if long else (entry - tp2) / risk
                break

    if exit_reason == "end_of_data":
        last = float(df["close"].iloc[end_bar])
        r = (last - entry) / risk if long else (entry - last) / risk

    return Trade(
        symbol=df.attrs.get("symbol", ""),
        pattern=signal.pattern_name, family=signal.family,
        direction=direction, entry_bar=entry_bar, entry_price=entry,
        stop_loss=stop, tp1=tp1, tp2=tp2,
        exit_bar=exit_bar, exit_price=exit_price,
        exit_reason=exit_reason, r_multiple=r,
        bars_held=exit_bar - entry_bar,
        grade=signal.grade, width_pct=signal.width_pct or 0.0,
    )


# --- Group runners ------------------------------------------------------------


# Anchor spacing: every 50 bars (~8.3 days). With 4385 bars and 50-bar
# spacing we have ~76 anchors per symbol — enough to surface trades across
# the 2-year window without doubling the detector cost on duplicates.
ANCHOR_STEP = 50
WINDOW = 1000


def run_symbol_group(
    symbol: str, df4: pd.DataFrame, daily_close: pd.Series,
    fresh: list[tuple[int, "Candidate"]] | None = None,
    min_grade: str = "C",  # include C(参考) so we have a tradable population
    group: str = "control",
    anchor_step: int = 20,
) -> list[Trade]:
    """Walk forward over the 4h series and generate trades for one group.

    Uses ``find_fresh_patterns`` to discover every anchor where an XABCD
    pattern just printed, then evaluates the engine + filters per group.

    ``fresh``: optional pre-computed list of (anchor, candidate) — pass it
    when running multiple groups against the same symbol to avoid re-running
    the detector three times.

    group:
        - 'control':        take every trade the signal_engine produces
        - 'strict':         + discipline_filters (path-integrity, TTL, TP2)
        - 'experimental':   + macro.size_mult (recorded for size-weighted P&L)
    """
    df4.attrs["symbol"] = symbol
    trades: list[Trade] = []

    if fresh is None:
        fresh = find_fresh_patterns(
            df4, symbol, anchor_step=anchor_step, max_age_bars=5, limit_to=20,
        )

    # Backtest-specific: the production engine's confluence_score expects
    # divergence + HTF data the backtest does not have. Without it, scores
    # land in the 5-42 range and ``grade()`` returns None for every pattern.
    # We monkeypatch ``grade`` here to drop the threshold so the harness can
    # compare strategy filters on the SAME candidate pool. This is a
    # documented deviation from production semantics; it does NOT change
    # runtime behaviour, only the backtest's signal construction.
    import app.services.signal_engine as _se_module
    _original_grade = _se_module.grade

    def _backtest_grade(score, rr_tp1, rr_tp2, htf_aligned, htf_counter,
                        a_min=75, width_pct=None):
        """Lower threshold: accept score >= 15 if RR gates pass."""
        if rr_tp1 is None or rr_tp2 is None:
            return None
        if width_pct is not None and width_pct >= 0.04:
            return "C(参考)" if score >= 15 else None
        if htf_counter:
            return "C(参考)" if score >= 15 else None
        if rr_tp1 < 1.0 or rr_tp2 < 1.5:
            return "C(参考)" if score >= 15 else None
        if score >= 60:
            return "B"
        if score >= 30:
            return "C(参考)"
        return None

    _se_module.grade = _backtest_grade
    try:
        for anchor, cand in fresh:
            sub = df4.iloc[: anchor + 1].reset_index(drop=True).copy()
            try:
                signal = build_signal(sub, "4h", [cand])
            except Exception:
                continue
            if signal is None:
                continue

            entry_bar = anchor + 1
            if entry_bar >= len(df4):
                continue

            # Discipline: for formed candidates, only ``past_tp2`` applies
            # (the trade played out before we could enter). The
            # ``breached_stop`` / path-integrity gate is for FORMING
            # candidates — it asserts the PRZ hasn't been touched by
            # subsequent price action. On a formed candidate that's by
            # definition false-positive (the pattern completed, so the
            # bars after C include D itself and the trade outcomes).
            verdict = discipline_evaluate(
                df4, cand, float(df4["close"].iloc[entry_bar]),
            )
            # Point-in-time macro: only pass daily closes up to the
            # entry bar. Using the full series is forward-looking bias —
            # the EMA200 at end-of-data reflects the eventual outcome,
            # not what a trader saw at pattern detection.
            daily_pt = daily_close.iloc[: daily_close.index.searchsorted(
                df4["dts"].iloc[anchor + 1],
            ) + 1] if hasattr(daily_close, "index") else daily_close.iloc[:anchor+1]
            macro = macro_compute(daily_pt, 1 if cand.bullish else -1)
            accept = True
            if group in ("strict", "experimental"):
                if cand.formed:
                    # For formed: only drop when price has already crossed
                    # TP2 — the trade is moot.
                    if verdict.metrics.past_tp2:
                        accept = False
                else:
                    if not verdict.passed:
                        accept = False
            if not accept:
                continue

            trade = _simulate_trade(df4, entry_bar, signal)
            trade.discipline_passed = verdict.passed
            trade.macro_size_mult = (
                macro.size_mult if group == "experimental" else 1.0
            )
            trade.group = group
            trades.append(trade)
    finally:
        _se_module.grade = _original_grade

    return trades


def aggregate(trades: list[Trade]) -> dict:
    """Compute aggregate metrics from a list of trades."""
    if not trades:
        return {
            "trades_count": 0, "win_rate": 0.0, "avg_r": 0.0,
            "total_r": 0.0, "total_weighted_r": 0.0,
            "profit_factor": None, "max_dd_r": 0.0,
            "avg_bars_held": 0.0,
            "by_grade": {},
            "by_exit_reason": {},
        }
    wins = [t for t in trades if t.r_multiple > 0]
    losses = [t for t in trades if t.r_multiple < 0]
    scratches = [t for t in trades if t.r_multiple == 0]
    total_r = sum(t.r_multiple for t in trades)
    total_w = sum(t.r_multiple * t.macro_size_mult for t in trades)
    gross_win = sum(t.r_multiple for t in wins)
    gross_loss = abs(sum(t.r_multiple for t in losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else None

    # Draw-down on cumulative R.
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cum += t.r_multiple
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    by_grade: dict[str, dict] = {}
    for t in trades:
        g = t.grade
        if g not in by_grade:
            by_grade[g] = {"n": 0, "total_r": 0.0, "wins": 0}
        by_grade[g]["n"] += 1
        by_grade[g]["total_r"] += t.r_multiple
        if t.r_multiple > 0:
            by_grade[g]["wins"] += 1

    by_exit: dict[str, int] = {}
    for t in trades:
        by_exit[t.exit_reason] = by_exit.get(t.exit_reason, 0) + 1

    return {
        "trades_count": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "scratch_count": len(scratches),
        "win_rate": len(wins) / len(trades),
        "avg_r": total_r / len(trades),
        "total_r": total_r,
        "total_weighted_r": total_w,
        "profit_factor": pf,
        "max_dd_r": max_dd,
        "avg_bars_held": sum(t.bars_held for t in trades) / len(trades),
        "by_grade": by_grade,
        "by_exit_reason": by_exit,
    }


# --- Main -------------------------------------------------------------------


def main():
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)

    summary: dict = {}
    for csv in sorted(os.listdir(data_dir)):
        if not csv.endswith("_1h.csv"):
            continue
        symbol = csv.replace("_1h.csv", "").upper()
        path = os.path.join(data_dir, csv)
        print(f"\n=== {symbol} ===")
        df4 = load_4h(path)
        daily = to_daily_close(df4)
        print(f"  4h bars: {len(df4)} | daily bars: {len(daily)}")

        # Run the detector once per symbol (shared across all three groups).
        t_det = time.time()
        fresh = find_fresh_patterns(df4, symbol, anchor_step=20, max_age_bars=5)
        print(f"  detector: {len(fresh)} fresh XABCD patterns [{time.time() - t_det:.1f}s]")

        all_trades: dict[str, list] = {}
        for group in ("control", "strict", "experimental"):
            t0 = time.time()
            trades = run_symbol_group(
                symbol, df4, daily, fresh=fresh, group=group,
            )
            elapsed = time.time() - t0
            metrics = aggregate(trades)
            all_trades[group] = trades
            print(f"  {group:14s}: {metrics['trades_count']:3d} trades  "
                  f"avg_r={metrics['avg_r']:+.3f}  "
                  f"total_r={metrics['total_r']:+.1f}  "
                  f"weighted_r={metrics['total_weighted_r']:+.2f}  "
                  f"win_rate={metrics['win_rate']:.0%}  "
                  f"[{elapsed:.1f}s]")

        summary[symbol] = {
            group: aggregate(all_trades[group]) for group in all_trades
        }

    out_path = os.path.join(out_dir, "summary.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nSummary → {out_path}")


if __name__ == "__main__":
    main()
