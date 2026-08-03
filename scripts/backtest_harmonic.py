#!/usr/bin/env python3
"""CLI: run a walk-forward harmonic backtest and emit JSON + Markdown artifacts.

Examples:
    PYTHONPATH=. python scripts/backtest_harmonic.py \
        --symbol BTCUSDT --interval 1d --days 90 \
        --window 30 --step 1 --horizon 30 \
        --out-dir docs/_backtest_artifacts

Defaults match a Binance BTCUSDT 1d walk-forward over the last 90 calendar
days with a 30-bar window, 1-bar step, and a 30-bar forward horizon.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Make ``app.*`` importable when invoked from the repo root without install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._binance_stdlib import fetch_binance_klines as _fetch_binance_stdlib
from scripts.backtest_harmonic_lib import (
    aggregate_records,
    markdown_summary,
    report,
    walk_forward,
    write_json,
)


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--window", type=int, default=30, help="rolling window bars")
    parser.add_argument("--step", type=int, default=1, help="bars advanced per step")
    parser.add_argument("--horizon", type=int, default=30, help="forward bars evaluated")
    parser.add_argument(
        "--out-dir",
        default="docs/_backtest_artifacts",
        help="directory to write JSON + Markdown artifacts into",
    )
    parser.add_argument("--silent", action="store_true")
    parser.add_argument(
        "--data-loader",
        choices=["prod", "stdlib", "cache"],
        default="cache",
        help=(
            "prod = app.infra.historical_data (uses curl_cffi; may hang on TLS in "
            "some envs); stdlib = urllib-only Binance fetch; "
            "cache = local Parquet cache (default, fastest for repeated runs)."
        ),
    )
    parser.add_argument(
        "--entry-mode",
        choices=["market", "prz"],
        default="prz",
        help=(
            "market = enter at window-close (most signals skip when price has "
            "already run past the PRZ). prz = enter at signal.entry_reference "
            "(matches live trader semantic of waiting for pullback; default)."
        ),
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Fetch fetch_days + 7 safety margin so the forward horizon never wraps.
    fetch_days = args.days + 7

    if not args.silent:
        print(
            f"[backtest] fetching {args.symbol} {args.interval} {args.days}d "
            f"(window={args.window} step={args.step} horizon={args.horizon})"
        )
    t0 = time.time()
    if args.data_loader == "prod":
        from app.infra.historical_data import fetch_historical_data

        df = fetch_historical_data("binance", args.symbol, args.interval, fetch_days)
    elif args.data_loader == "cache":
        # Try to load from local cache first, download if not available.
        from scripts.download_backtest_data import ensure_data

        df, was_cached = ensure_data(
            args.symbol,
            args.interval,
            days=fetch_days,
            exchange="binance",
            verbose=not args.silent,
        )
        if not args.silent:
            print(f"[backtest] data source: {'cache' if was_cached else 'downloaded'}")
    else:
        from datetime import datetime, timedelta, timezone

        # Pin end-date so sliding-window backtests are reproducible across
        # reruns (the walk_forward engine consumes the last window-end candle
        # as the signal timestamp; using ``datetime.now()`` would make
        # successive matrix runs see slightly different data slices).
        end = datetime(2026, 8, 1, tzinfo=timezone.utc)
        start = end - timedelta(days=fetch_days)
        df = _fetch_binance_stdlib(args.symbol, args.interval, start, end)
    elapsed_fetch = time.time() - t0
    if df is None or df.empty:
        raise SystemExit("No historical data returned")

    if not args.silent:
        print(
            f"[backtest] {len(df)} candles: {df.index[0]} -> {df.index[-1]} "
            f"({elapsed_fetch:.1f}s, loader={args.data_loader})"
        )

    t0 = time.time()
    records = walk_forward(
        df,
        args.symbol,
        args.interval,
        window=args.window,
        step=args.step,
        horizon=args.horizon,
        entry_mode=args.entry_mode,
    )
    elapsed_walk = time.time() - t0

    summary = aggregate_records(records)
    config = {
        "market": "binance",
        "symbol": args.symbol,
        "interval": args.interval,
        "days": args.days,
        "window": args.window,
        "step": args.step,
        "horizon": args.horizon,
        "fetch_days": fetch_days,
        "candles_fetched": len(df),
        "data_start": df.index[0].isoformat(),
        "data_end": df.index[-1].isoformat(),
        "elapsed_fetch_seconds": round(elapsed_fetch, 2),
        "elapsed_walk_seconds": round(elapsed_walk, 2),
        "llm_disabled": True,
        "data_loader": args.data_loader,
        "entry_mode": args.entry_mode,
    }
    rep = report(config=config, summary=summary, records=records)
    slug = f"{args.symbol}_{args.interval}_{args.days}d"
    json_path = out_dir / f"{slug}.json"
    md_path = out_dir / f"{slug}.md"
    write_json(rep, json_path)
    md_path.write_text(markdown_summary(rep))

    if not args.silent:
        print(json_path)
        print(md_path)
        s = rep["summary"]
        print(
            f"[backtest] {s['total_signals']} signals, "
            f"win_rate={s['win_rate']:.1%} avg_r={s['avg_r']:+.2f} "
            f"profit_factor={s['profit_factor'] if s['profit_factor'] != float('inf') else 'inf'} "
            f"({elapsed_walk:.1f}s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
