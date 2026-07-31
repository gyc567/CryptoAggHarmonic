"""Bench runner: end-to-end CLI for HarmonicSignal-Bench.

Mirrors ``scripts/backtest_harmonic.py`` semantics for fetching + walk-forward,
then layers on the bench pipeline: convert to SignalRecord, run Stage 1/3/4b,
aggregate per-pattern, emit CSV + leaderboard JSON + charts.

The Stage 4a callback path is intentionally skipped in v1 because it requires
the per-record forward OHLC slice (trade_metrics.apply_trade_metrics needs the
forward dataframe + entry bar). Stage 4a can be wired in a follow-up by
slicing ``df.iloc[entry_idx + 1 : entry_idx + 1 + horizon]`` per record; for
now records carry ``stage4a_score = 0`` and the per-pattern breakdown still
reaches all four weighting slots. Leaving it 0 is honest: 0 is what the score
should be when the callback data isn't available.

Example:
    PYTHONPATH=. python -m bench.runner \\
        --symbol BTCUSDT --interval 1d --days 90 \\
        --window 30 --step 1 --horizon 30 \\
        --out-dir docs/_bench_artifacts
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Optional

from bench.dataset.signal_record import Outcome, SignalRecord
from bench.pipeline.stage1_validity import stage1_score
from bench.pipeline.stage3_outcome import stage3_score
from bench.pipeline.stage4b_technical import stage4b_score
from bench.report.charts import render_all
from bench.report.csv_writer import write_csv
from bench.report.leaderboard import write_leaderboard
from bench.scoring.aggregator import (
    AggregatorResult,
    aggregate,
)
from bench.scoring.confidence import wilson_ci
from bench.scoring.pareto import BenchAugmentedParetoPoint
from app.loop.pareto import ParetoPoint


# --- Constants ---------------------------------------------------------------

MARKET_DEFAULT = "binance"
SYNTHETIC_ATR = 2.0
SYNTHETIC_PRZ_WIDTH = 0.3
SYNTHETIC_ENTRY_OFFSET = 0.0
SYNTHETIC_CONFLUENCE = 0.0
SYNTHETIC_STABILITY = ""
SYNTHETIC_REGIME = ""
SYNTHETIC_VOLUME_AUTH = 0.0


# --- Result mapping ----------------------------------------------------------

_RESULT_TO_OUTCOME: dict[str, Outcome] = {
    "win": "tp2",      # ambiguous win → tp2 (middle of ladder)
    "loss": "stoploss",
    "scratch": "breakeven",
    "skipped": "incomplete",
}


# --- DTOs --------------------------------------------------------------------

@dataclass
class ChartPaths:
    """All chart paths produced by ``run_bench``.

    Empty lists when ``out_dir`` is None.
    """
    dir: str = ""
    paths: List[str] = field(default_factory=list)


@dataclass
class BenchRunResult:
    """Returned from ``run_bench``. Carries counts + paths for tests + CLI."""

    config_id: str
    symbol: str
    interval: str
    days: int
    window: int
    step: int
    horizon: int
    market: str
    n_records: int
    n_wins: int
    n_losses: int
    n_scratches: int
    n_skipped: int
    signal_score: float
    config_score: Optional[float]
    bench_total: float
    weak_validity: bool
    low_confidence: bool
    n_patterns: int
    csv_path: Optional[str]
    leaderboard_path: Optional[str]
    charts: ChartPaths
    elapsed_seconds: float


# --- Field mapping -----------------------------------------------------------

def _signal_record_from_backtest(
    src: Any,
    symbol: str,
    interval: str,
) -> SignalRecord:
    """Convert a ``BacktestSignalRecord`` to a bench ``SignalRecord``.

    Fields not surfaced by the underlying backtest get synthetic defaults
    (documented in runner docstring).
    """
    outcome = _RESULT_TO_OUTCOME.get(src.result, "incomplete")
    return SignalRecord(
        signal_id=f"{src.signal_time}_{src.step_index}",
        run_id="bench_runner",
        params_sha="runner_default",
        timestamp=src.signal_time,
        symbol=symbol,
        timeframe=interval,
        pattern_type=src.pattern_name or "unknown",
        pattern_family=src.family or "XABCD",
        direction=src.direction,
        grade=src.grade,
        entry_price=src.entry_price,
        stop_price=src.stop_loss,
        tp1=src.tp1,
        tp2=0.0,
        tp3=0.0,
        atr_at_entry=SYNTHETIC_ATR,
        prz_width_atr=SYNTHETIC_PRZ_WIDTH,
        entry_offset_atr=SYNTHETIC_ENTRY_OFFSET,
        confluence_score=SYNTHETIC_CONFLUENCE,
        stability_verdict=SYNTHETIC_STABILITY,
        regime=SYNTHETIC_REGIME,
        volume_authenticity_score=SYNTHETIC_VOLUME_AUTH,
        outcome=outcome,
        net_rr=src.r_multiple,
        bars_held=src.bars_held,
        exit_price=None,
        exit_reason=src.result,
    )


def convert_records(
    records: Iterable,
    symbol: str,
    interval: str,
) -> List[SignalRecord]:
    """Convert an iterable of ``BacktestSignalRecord`` to SignalRecord."""
    return [_signal_record_from_backtest(r, symbol, interval) for r in records]


# --- Pipeline ----------------------------------------------------------------

def run_pipeline(
    records: List[SignalRecord],
) -> AggregatorResult:
    """Run Stages 1/3/4b in-place on each record, then aggregate per-pattern."""
    for rec in records:
        stage1_score(rec)
        stage3_score(rec)
        stage4b_score(rec)
        # stage4a / trade_metrics intentionally skipped in v1 (see module docstring).
        rec.stage4a_score = 0.0
    return aggregate(records)


def _count_by_result(records: Iterable) -> dict:
    counts = {"win": 0, "loss": 0, "scratch": 0, "skipped": 0}
    for r in records:
        if r.result in counts:
            counts[r.result] += 1
    return counts


# --- Orchestrator ------------------------------------------------------------

def run_bench(
    *,
    walk_forward_fn,
    symbol: str,
    interval: str,
    days: int,
    window: int,
    step: int,
    horizon: int,
    out_dir: Optional[Path] = None,
    config_id: Optional[str] = None,
    market: str = MARKET_DEFAULT,
) -> BenchRunResult:
    """Fetch + walk-forward + bench scoring + optional artifacts.

    Args:
        walk_forward_fn: Callable matching ``scripts.backtest_harmonic_lib.walk_forward``
            signature. Injected so tests can mock without I/O.
        symbol, interval, days, window, step, horizon: Backtest params.
        out_dir: If provided, write CSV + leaderboard + charts.
        config_id: Stable name for this run (auto-generated if None).
        market: Market tag for the config block.

    Returns a ``BenchRunResult`` with paths (or ``None`` if ``out_dir`` is None).
    """
    config_id = config_id or f"{symbol}_{interval}_{days}d"
    out_dir_p = Path(out_dir) if out_dir is not None else None

    t0 = time.time()
    # fetch_days = days + 7 (matches scripts/backtest_harmonic.py safety margin).
    fetch_days = days + 7

    from app.infra.historical_data import fetch_historical_data
    df = fetch_historical_data(market, symbol, interval, fetch_days)
    if df is None or df.empty:
        raise SystemExit("No historical data returned")

    records = walk_forward_fn(
        df, symbol, interval,
        window=window, step=step, horizon=horizon,
    )

    sig_records = convert_records(records, symbol, interval)
    agg = run_pipeline(sig_records)

    counts = _count_by_result(records)

    csv_path: Optional[str] = None
    leaderboard_path: Optional[str] = None
    charts = ChartPaths()
    if out_dir_p is not None:
        out_dir_p.mkdir(parents=True, exist_ok=True)
        csv_path = str(out_dir_p / f"{config_id}.csv")
        leaderboard_path = str(out_dir_p / f"{config_id}_leaderboard.json")
        write_csv(sig_records, Path(csv_path))
        # Build a single bench-augmented Pareto point for this run.
        n_total = sum(1 for r in sig_records if r.outcome)
        n_wins = sum(1 for r in sig_records if r.outcome in ("tp1", "tp2", "tp3"))
        win_rate = (n_wins / n_total) if n_total else 0.0
        ci = wilson_ci(n_wins, n_total)
        base_pt = ParetoPoint(
            params_sha=config_id,
            gen=0,
            cluster="bench_runner",
            run_dir=str(out_dir_p),
            sharpe=None,
            calmar=None,
            profit_factor=None,
            worst_regime_sharpe=None,
            trade_count=n_total,
            fitness=agg["bench_total"],
        )
        low_sample_patterns = [
            p["pattern_family"] for p in agg["pattern_scores"]
            if p["signal_count"] < 10
        ]
        points = [BenchAugmentedParetoPoint(
            base=base_pt,
            signal_score=agg["signal_score"],
            config_score=agg["config_score"],
            bench_total=agg["bench_total"],
            low_confidence=agg["low_confidence"],
            n_signals=agg["n_signals"],
            win_rate=round(win_rate, 4),
            win_rate_ci=ci,
            warnings=list(low_sample_patterns),
        )]
        write_leaderboard(
            str(leaderboard_path),
            points=points,
            low_confidence=agg["low_confidence"],
            warnings=low_sample_patterns,
            extra={
                "config_id": config_id,
                "symbol": symbol,
                "interval": interval,
                "days": days,
                "window": window,
                "step": step,
                "horizon": horizon,
                "n_wins": counts["win"],
                "n_losses": counts["loss"],
                "n_scratches": counts["scratch"],
                "n_skipped": counts["skipped"],
                "n_patterns": agg["n_patterns"],
            },
        )
        # pareto front needs at least one point; fall back to an empty list.
        # (render_all skips the front-level chart if no points provided.)
        chart_paths = render_all(sig_records, [], str(out_dir_p))
        charts = ChartPaths(dir=str(out_dir_p), paths=chart_paths)

    elapsed = time.time() - t0
    return BenchRunResult(
        config_id=config_id,
        symbol=symbol,
        interval=interval,
        days=days,
        window=window,
        step=step,
        horizon=horizon,
        market=market,
        n_records=len(sig_records),
        n_wins=counts["win"],
        n_losses=counts["loss"],
        n_scratches=counts["scratch"],
        n_skipped=counts["skipped"],
        signal_score=agg["signal_score"],
        config_score=agg["config_score"],
        bench_total=agg["bench_total"],
        weak_validity=agg["weak_validity"],
        low_confidence=agg["low_confidence"],
        n_patterns=agg["n_patterns"],
        csv_path=csv_path,
        leaderboard_path=leaderboard_path,
        charts=charts,
        elapsed_seconds=round(elapsed, 2),
    )


# --- CLI ---------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="HarmonicSignal-Bench runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--interval", default="1d")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--window", type=int, default=30, help="rolling window bars")
    p.add_argument("--step", type=int, default=1, help="bars advanced per step")
    p.add_argument("--horizon", type=int, default=30, help="forward bars evaluated")
    p.add_argument("--market", default=MARKET_DEFAULT)
    p.add_argument(
        "--out-dir",
        default="docs/_bench_artifacts",
        help="directory for CSV + leaderboard + charts (empty disables writes)",
    )
    p.add_argument(
        "--config-id",
        default=None,
        help="stable name for this run (defaults to <symbol>_<interval>_<days>d)",
    )
    p.add_argument(
        "--no-write",
        action="store_true",
        help="skip writing CSV/leaderboard/charts (useful for tests)",
    )
    p.add_argument("--silent", action="store_true")
    return p


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    from scripts.backtest_harmonic_lib import walk_forward

    out_dir = None if args.no_write else Path(args.out_dir)
    if out_dir is not None and not out_dir.exists() and not args.silent:
        print(f"[bench] {out_dir} does not exist yet; will create", file=sys.stderr)

    if not args.silent:
        print(
            f"[bench] {args.symbol} {args.interval} {args.days}d "
            f"window={args.window} step={args.step} horizon={args.horizon}"
        )

    res = run_bench(
        walk_forward_fn=walk_forward,
        symbol=args.symbol,
        interval=args.interval,
        days=args.days,
        window=args.window,
        step=args.step,
        horizon=args.horizon,
        out_dir=out_dir,
        config_id=args.config_id,
        market=args.market,
    )

    if not args.silent:
        if res.csv_path:
            print(f"[bench] csv: {res.csv_path}")
        if res.leaderboard_path:
            print(f"[bench] leaderboard: {res.leaderboard_path}")
        if res.charts.paths:
            print(f"[bench] charts: {res.charts.dir}")
        print(
            f"[bench] {res.n_records} signals | "
            f"signal={res.signal_score:.1f} "
            f"config={res.config_score if res.config_score is not None else float('nan'):.1f} "
            f"bench_total={res.bench_total:.1f} "
            f"({res.elapsed_seconds:.1f}s)"
        )
    return 0


__all__ = [
    "BenchRunResult",
    "convert_records",
    "run_bench",
    "run_pipeline",
    "build_parser",
    "main",
]