"""Multi-objective fitness + walk-forward + regime-bucket backtest harness.

Built on top of the v2 single-symbol harness. Differences:

* Multi-objective fitness: per-group sharpe, calmar, sortino, profit_factor,
  max drawdown, worst-regime sharpe (NOT just total R).
* Walk-forward by quarter: ``--quarter YYYY-Qq`` restricts data to a single
  quarter for OOS-style evaluation; default = full window.
* Regime buckets: trades are tagged by macro regime at entry (bull / bear /
  range); per-bucket metrics are reported separately so a parameter set that
  wins in one regime at the cost of another is visible.
* ``--tuning-yaml PATH``: load a :class:`TuningConstants` from YAML and apply
  it to every consumer module before running the simulation. Without this
  flag the harness uses the production ``TUNING`` singleton (zero behaviour
  change vs. the v2 harness).

Three strategy groups as before: ``control`` / ``strict`` / ``experimental``.
"""
from __future__ import annotations

import argparse
import json
import math
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

from app.config.tuning import (
    TUNING,
    apply_tuning,
    reset_tuning,
    from_dict,
    to_dict,
    tuning_scope,
)
from app.domain.signals import Candidate
from app.services.signal_engine import build_signal, extract_candidates
from app.services.discipline_filters import evaluate as discipline_evaluate
from app.services.macro_bias import compute as macro_compute


# --- Data loading (same as v2 harness) ----------------------------------------


def load_4h(csv_path: str) -> pd.DataFrame:
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
    return (
        df4.set_index("dts")["close"]
        .resample("1d")
        .last()
        .dropna()
    )


def quarter_mask(df4: pd.DataFrame, quarter: Optional[str]) -> pd.DataFrame:
    """Restrict df4 to a single quarter if ``quarter`` is given.

    ``quarter`` format: ``YYYY-Qq`` (e.g. ``2024-Q1``). Returns the original
    df4 unchanged when None.
    """
    if quarter is None:
        return df4
    year_str, q_str = quarter.split("-Q")
    year, q = int(year_str), int(q_str)
    start = pd.Timestamp(year=year, month=(q - 1) * 3 + 1, day=1, tz="UTC")
    end = start + pd.QuarterEnd(1)
    return df4[(df4["dts"] >= start) & (df4["dts"] <= end)].reset_index(drop=True)


# --- Detector ----------------------------------------------------------------


def find_fresh_patterns(
    df: pd.DataFrame, symbol: str, anchor_step: int = 20,
    max_age_bars: int = 5, limit_to: int = 20,
) -> list[tuple[int, "Candidate"]]:
    found: list[tuple[int, Candidate]] = []
    for anchor in range(200, len(df) - 50, anchor_step):
        sub = df.iloc[: anchor + 1].reset_index(drop=True).copy()
        if len(sub) < 200:
            continue
        try:
            from pyharmonics.technicals import OHLCTechnicals
            from pyharmonics.search import HarmonicSearch

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
            d_time = cand.times[-1]
            last_close_time = sub["close_time"].iloc[last_sub_idx]
            age_sec = last_close_time - d_time
            age_bars = age_sec / 14400.0
            if age_bars <= max_age_bars:
                found.append((anchor, cand))
    return found


# --- Trade + simulator -------------------------------------------------------


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
    macro_regime: str = "unknown"
    discipline_passed: bool = True
    group: str = ""


def _simulate_trade(
    df: pd.DataFrame, entry_bar: int, signal, max_hold_bars: int = 100,
) -> Trade:
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
        if stop_hit:
            exit_bar = i
            exit_price = stop
            exit_reason = "stop_loss"
            r = -1.0
            break
        if tp1 is not None:
            tp1_hit = (high >= tp1) if long else (low <= tp1)
            if tp1_hit:
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


# --- Group runner ------------------------------------------------------------


def run_symbol_group(
    symbol: str, df4: pd.DataFrame, daily_close: pd.Series,
    fresh: list[tuple[int, "Candidate"]] | None = None,
    group: str = "control",
    anchor_step: int = 20,
) -> list[Trade]:
    df4.attrs["symbol"] = symbol
    trades: list[Trade] = []

    if fresh is None:
        fresh = find_fresh_patterns(
            df4, symbol, anchor_step=anchor_step, max_age_bars=5, limit_to=20,
        )

    # Same backtest-specific grade monkeypatch as v2 (see REPORT.md).
    import app.services.signal_engine as _se_module
    _original_grade = _se_module.grade

    def _backtest_grade(score, rr_tp1, rr_tp2, htf_aligned, htf_counter,
                        a_min=75, width_pct=None):
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

            verdict = discipline_evaluate(
                df4, cand, float(df4["close"].iloc[entry_bar]),
            )
            daily_pt = daily_close.iloc[: daily_close.index.searchsorted(
                df4["dts"].iloc[anchor + 1],
            ) + 1] if hasattr(daily_close, "index") else daily_close.iloc[:anchor+1]
            macro = macro_compute(daily_pt, 1 if cand.bullish else -1)
            accept = True
            if group in ("strict", "experimental"):
                if cand.formed:
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
            trade.macro_regime = macro.macro_dir
            trade.group = group
            trades.append(trade)
    finally:
        _se_module.grade = _original_grade

    return trades


# --- Multi-objective aggregation ---------------------------------------------


def _sharpe(rs: list[float]) -> Optional[float]:
    """Sharpe (no annualization) over per-trade R-multiples.

    Returns None when fewer than 3 trades or zero variance.
    """
    if len(rs) < 3:
        return None
    mean = sum(rs) / len(rs)
    var = sum((r - mean) ** 2 for r in rs) / (len(rs) - 1)
    if var <= 1e-12:
        return None
    return mean / math.sqrt(var)


def _sortino(rs: list[float]) -> Optional[float]:
    """Sortino: downside deviation only (R < 0)."""
    if len(rs) < 3:
        return None
    mean = sum(rs) / len(rs)
    downside = [r for r in rs if r < 0]
    if not downside:
        return None
    var = sum(r * r for r in downside) / len(downside)
    if var <= 1e-12:
        return None
    return mean / math.sqrt(var)


def _calmar(rs: list[float]) -> Optional[float]:
    """Calmar = total R / max drawdown in R units. None when DD == 0."""
    if not rs:
        return None
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    if max_dd <= 1e-9:
        return None
    return sum(rs) / max_dd


def _profit_factor(rs: list[float]) -> Optional[float]:
    wins = sum(r for r in rs if r > 0)
    losses = abs(sum(r for r in rs if r < 0))
    if losses <= 1e-9:
        return None
    return wins / losses


def aggregate(trades: list[Trade]) -> dict:
    if not trades:
        return _empty_metrics()
    rs = [t.r_multiple for t in trades]
    wins = [t for t in trades if t.r_multiple > 0]
    losses = [t for t in trades if t.r_multiple < 0]
    scratches = [t for t in trades if t.r_multiple == 0]
    total_r = sum(rs)
    total_w = sum(t.r_multiple * t.macro_size_mult for t in trades)

    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        cum += r
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

    # Regime buckets — tag from macro_regime on each trade.
    by_regime: dict[str, dict] = {}
    for t in trades:
        regime = t.macro_regime or "unknown"
        bucket = by_regime.setdefault(
            regime, {"n": 0, "total_r": 0.0, "wins": 0, "rs": []}
        )
        bucket["n"] += 1
        bucket["total_r"] += t.r_multiple
        bucket["rs"].append(t.r_multiple)
        if t.r_multiple > 0:
            bucket["wins"] += 1
    for b in by_regime.values():
        rs_b = b.pop("rs")
        b["sharpe"] = _sharpe(rs_b)
        b["win_rate"] = b["wins"] / b["n"] if b["n"] > 0 else 0.0

    return {
        "trades_count": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "scratch_count": len(scratches),
        "win_rate": len(wins) / len(trades),
        "avg_r": total_r / len(trades),
        "total_r": total_r,
        "total_weighted_r": total_w,
        "sharpe": _sharpe(rs),
        "sortino": _sortino(rs),
        "calmar": _calmar(rs),
        "profit_factor": _profit_factor(rs),
        "max_dd_r": max_dd,
        "avg_bars_held": sum(t.bars_held for t in trades) / len(trades),
        "by_grade": by_grade,
        "by_exit_reason": by_exit,
        "by_regime": by_regime,
    }


def _empty_metrics() -> dict:
    return {
        "trades_count": 0, "win_count": 0, "loss_count": 0,
        "scratch_count": 0, "win_rate": 0.0, "avg_r": 0.0,
        "total_r": 0.0, "total_weighted_r": 0.0,
        "sharpe": None, "sortino": None, "calmar": None,
        "profit_factor": None, "max_dd_r": 0.0,
        "avg_bars_held": 0.0, "by_grade": {}, "by_exit_reason": {},
        "by_regime": {},
    }


def fitness(metrics: dict) -> float:
    """Composite fitness used by the loop's per-cluster search.

    Combines risk-adjusted return + regime robustness - drawdown penalty +
    sample-size incentive. See loop-tuning plan §5d.
    """
    if metrics["trades_count"] < 10:
        return -1e6  # not enough data; reject
    sharpe = metrics["sharpe"] or 0.0
    calmar = metrics["calmar"] or 0.0
    pf = metrics["profit_factor"] or 0.0

    # Worst-regime sharpe (penalise regime collapse)
    regime_sharpes = [
        b.get("sharpe") or 0.0
        for b in metrics.get("by_regime", {}).values()
        if b.get("n", 0) >= 3
    ]
    worst_regime = min(regime_sharpes) if regime_sharpes else 0.0

    return (
        + 1.0 * sharpe
        + 0.5 * calmar
        + 0.3 * pf
        - 1.0 * max(0, -worst_regime)
        + 0.05 * math.log(max(metrics["trades_count"], 1))
    )


# --- CLI ----------------------------------------------------------------------


def _load_tuning(path: Optional[str]):
    if path is None:
        return None
    import yaml

    with open(path) as f:
        d = yaml.safe_load(f)
    return from_dict(d or {})


def main():
    p = argparse.ArgumentParser(description="v3 multi-objective backtest harness")
    p.add_argument(
        "--data-dir", default=os.path.join(os.path.dirname(__file__), "data"),
        help="Directory holding <SYMBOL>_1h.csv files (Coinbase format).",
    )
    p.add_argument(
        "--out-dir", default=os.path.join(os.path.dirname(__file__), "results"),
        help="Directory for summary.json + trades.json output.",
    )
    p.add_argument(
        "--symbol-set", default="BTCUSD,ETHUSD,SOLUSD",
        help="Comma-separated subset of symbols to run.",
    )
    p.add_argument(
        "--quarter", default=None,
        help="Optional YYYY-Qq (e.g. 2024-Q2) to restrict data for OOS eval.",
    )
    p.add_argument(
        "--tuning-yaml", default=None,
        help="YAML file describing a TuningConstants instance to load.",
    )
    p.add_argument(
        "--anchor-step", type=int, default=20,
        help="Detector anchor spacing in bars (lower = more patterns, slower).",
    )
    args = p.parse_args()

    tuning = _load_tuning(args.tuning_yaml)
    if tuning is not None:
        apply_tuning(tuning)
        print(f"Loaded tuning from {args.tuning_yaml}")
    else:
        print("Using production TUNING singleton (default values)")

    os.makedirs(args.out_dir, exist_ok=True)
    symbols = [s.upper() for s in args.symbol_set.split(",") if s.strip()]

    summary: dict = {}
    all_trades: dict[str, list[Trade]] = {"control": [], "strict": [], "experimental": []}

    try:
        for csv in sorted(os.listdir(args.data_dir)):
            if not csv.endswith("_1h.csv"):
                continue
            base = csv.replace("_1h.csv", "").upper()
            # Match against symbol set (csv base like BTCUSD, symbol BTCUSD)
            if not any(base.startswith(s.replace("USD", "")) for s in symbols):
                continue
            symbol = base
            path = os.path.join(args.data_dir, csv)
            print(f"\n=== {symbol} ===")
            df4 = load_4h(path)
            df4 = quarter_mask(df4, args.quarter)
            if len(df4) < 300:
                print(f"  skip: only {len(df4)} bars after quarter mask")
                continue
            daily = to_daily_close(df4)
            print(f"  4h bars: {len(df4)} | daily bars: {len(daily)}")

            t_det = time.time()
            fresh = find_fresh_patterns(
                df4, symbol, anchor_step=args.anchor_step, max_age_bars=5,
            )
            print(f"  detector: {len(fresh)} fresh XABCD patterns "
                  f"[{time.time() - t_det:.1f}s]")

            sym_trades: dict[str, list] = {}
            for group in ("control", "strict", "experimental"):
                t0 = time.time()
                trades = run_symbol_group(
                    symbol, df4, daily, fresh=fresh, group=group,
                    anchor_step=args.anchor_step,
                )
                elapsed = time.time() - t0
                metrics = aggregate(trades)
                sym_trades[group] = trades
                all_trades[group].extend(trades)
                m = metrics
                print(f"  {group:14s}: {m['trades_count']:3d} trades  "
                      f"avg_r={m['avg_r']:+.3f}  "
                      f"sharpe={_fmt(m['sharpe'])}  "
                      f"calmar={_fmt(m['calmar'])}  "
                      f"PF={_fmt(m['profit_factor'])}  "
                      f"WR={m['win_rate']:.0%}  "
                      f"[{elapsed:.1f}s]")

            summary[symbol] = {
                group: aggregate(sym_trades[group]) for group in sym_trades
            }

        # Aggregate across all requested symbols.
        agg_all: dict[str, dict] = {}
        for group in ("control", "strict", "experimental"):
            agg_all[group] = aggregate(all_trades[group])

        summary["__aggregate__"] = agg_all
        summary["__meta__"] = {
            "tuning_yaml": args.tuning_yaml,
            "quarter": args.quarter,
            "symbols": symbols,
            "fitness": {g: fitness(agg_all[g]) for g in ("control", "strict", "experimental")},
            "ts": time.time(),
        }

        out_path = os.path.join(args.out_dir, "summary.json")
        with open(out_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"\nSummary → {out_path}")

        # Per-trade ledger (one row per (symbol, group, trade)) for diagnostics.
        rows = []
        for group, ts in all_trades.items():
            for t in ts:
                rows.append({
                    "group": group,
                    "symbol": t.symbol,
                    "pattern": t.pattern,
                    "direction": t.direction,
                    "entry_bar": t.entry_bar,
                    "entry_price": t.entry_price,
                    "stop_loss": t.stop_loss,
                    "tp1": t.tp1,
                    "tp2": t.tp2,
                    "exit_bar": t.exit_bar,
                    "exit_price": t.exit_price,
                    "exit_reason": t.exit_reason,
                    "r_multiple": t.r_multiple,
                    "bars_held": t.bars_held,
                    "grade": t.grade,
                    "width_pct": t.width_pct,
                    "macro_size_mult": t.macro_size_mult,
                    "macro_regime": t.macro_regime,
                    "discipline_passed": t.discipline_passed,
                })
        ledger_path = os.path.join(args.out_dir, "trades.json")
        with open(ledger_path, "w") as f:
            json.dump(rows, f, indent=2)
        print(f"Trades  → {ledger_path}")

    finally:
        if tuning is not None:
            reset_tuning()


def _fmt(x):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:+.2f}"
    return str(x)


if __name__ == "__main__":
    main()