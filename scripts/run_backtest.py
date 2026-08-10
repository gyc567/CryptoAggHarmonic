#!/root/code/pyharmonics-gpt/.venv/bin/python
"""Daily backtest scheduler — run via cron at 20:00 UTC.

Runs walk-forward backtest across configured symbols, appends results to
``data/backtest_results.json``, and optionally writes a candidate tuning
snapshot to ``tuning_snapshots/`` for the human PR gate (ADR-003 D9).

Usage:
    ./scripts/run_backtest.py --symbols BTC/USDT ETH/USDT --snapshot
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── project root ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd

from scripts.backtest_harmonic_lib import (
    BacktestSignalRecord,
    aggregate_records,
    walk_forward,
)
from app.config.tuning import TUNING, to_dict
from app.loop.state import write_tuning_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT"]
DEFAULT_INTERVAL = "1h"
DEFAULT_START = "2024-01-01"
RESULT_DIR = ROOT / "data"
SNAPSHOT_DIR = ROOT / "tuning_snapshots"

# Columns required by backtest_harmonic_lib.detect_window / walk_forward.
OHLCV_COLS = ["open", "high", "low", "close", "volume"]
# Binance klines column layout (12 fields, we keep the first 6 + close_time).
BINANCE_KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_base",
    "taker_buy_quote", "ignore",
]
INTERVAL_MAP = {"15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"}


def _slice_range(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Filter cached candles to [start, end) using the dts column."""
    if "dts" not in df.columns or not start:
        return df
    t_start = pd.Timestamp(start, tz="UTC")
    t_end = pd.Timestamp(end, tz="UTC") if end else pd.Timestamp.max
    mask = (df["dts"] >= t_start) & (df["dts"] < t_end)
    return df[mask].copy()


def _load_history(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame:
    """Load cached parquet OHLCV data, else fetch from Binance public API.

    Cache lookup order:
      1. ``data/backtest/binance/{SYMBOL}/{interval}.parquet`` (managed by
         ``scripts/download_backtest_data.py``, reliable vision host)
      2. ``data/{SYMBOL}_{interval}.parquet`` (legacy ad-hoc cache)
    """
    # Managed cache (preferred) — matches download_backtest_data.py layout.
    managed = ROOT / "data" / "backtest" / "binance" / symbol.replace("/", "") / f"{interval}.parquet"
    if managed.exists():
        df = pd.read_parquet(managed)
        if len(df) > 0:
            df = _slice_range(df, start, end)
            log.info("Loaded %d candles from managed cache %s", len(df), managed)
            return df

    legacy = RESULT_DIR / f"{symbol.replace('/', '')}_{interval}.parquet"
    if legacy.exists():
        df = pd.read_parquet(legacy)
        if len(df) > 0:
            df = _slice_range(df, start, end)
            log.info("Loaded %d candles from legacy cache for %s", len(df), symbol)
            return df

    log.info("Fetching %s %s from Binance public API", symbol, interval)
    import httpx

    interval_k = INTERVAL_MAP.get(interval, "1h")
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
    base_url = "https://api.binance.com/api/v3/klines"

    rows: list[list] = []
    with httpx.Client(timeout=30) as client:
        cursor = start_ms
        while cursor < end_ms:
            r = client.get(
                base_url,
                params={
                    "symbol": symbol.replace("/", ""),
                    "interval": interval_k,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 1000,
                },
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            rows.extend(batch)
            cursor = int(batch[-1][0]) + 1
            time.sleep(0.25)

    if not rows:
        log.warning("No data returned for %s %s", symbol, interval)
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=BINANCE_KLINE_COLS)
    for c in OHLCV_COLS:
        df[c] = df[c].astype(float)
    df["close_time"] = df["close_time"].astype(int)
    df["dts"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    df = df[OHLCV_COLS + ["close_time", "dts"]]

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache)
    log.info("Fetched %d candles for %s, cached at %s", len(df), symbol, cache)
    return df


def _run_symbol(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    window: int,
    step: int,
    horizon: int,
    min_grade: str | None,
) -> list[BacktestSignalRecord]:
    """Run full walk-forward backtest for one symbol. Returns trade records."""
    log.info("Running walk-forward for %s %s [%s – %s]", symbol, interval, start, end)
    df = _load_history(symbol, interval, start, end)
    if len(df) < window + horizon + 1:
        log.warning(
            "Insufficient data for %s %s: %d rows (need %d)",
            symbol, interval, len(df), window + horizon + 1,
        )
        return []

    records: list[BacktestSignalRecord] = walk_forward(
        df,
        symbol=symbol,
        interval=interval,
        window=window,
        step=step,
        horizon=horizon,
        min_grade=min_grade,
    )
    log.info("%s %s: %d signals detected", symbol, interval, len(records))
    return records


def _run_symbol_aggregated(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    window: int,
    step: int,
    horizon: int,
    min_grade: str | None,
) -> tuple[str, dict]:
    """Worker: run walk-forward for one symbol, return (symbol, summary).

    Aggregates inside the worker so only a small summary dict crosses the
    process boundary (returning raw records blew the Pool pipe on long
    datasets).
    """
    records = _run_symbol(symbol, interval, start, end, window, step, horizon, min_grade)
    agg = aggregate_records(records) if records else {}
    return symbol, {"total": len(records), "aggregated": agg}


def run(
    symbols: list[str],
    interval: str,
    start: str,
    end: str,
    window: int,
    step: int,
    horizon: int,
    n_workers: int,
    min_grade: str | None,
) -> dict:
    """Run backtest across symbols in parallel, return aggregated results."""
    import multiprocessing

    tasks = [
        (s, interval, start, end, window, step, horizon, min_grade)
        for s in symbols
    ]
    if n_workers <= 1 or len(tasks) == 1:
        summaries = [_run_symbol_aggregated(*t) for t in tasks]
    else:
        with multiprocessing.Pool(n_workers) as pool:
            summaries = pool.starmap(_run_symbol_aggregated, tasks)

    by_symbol = dict(summaries)
    total_signals = sum(s["total"] for s in by_symbol.values())
    # Roll up per-symbol aggregates into one overall summary for the JSON.
    overall: dict = {"total_signals": total_signals}
    for s in by_symbol.values():
        for k, v in (s["aggregated"] or {}).items():
            if isinstance(v, (int, float)):
                overall[k] = overall.get(k, 0) + v
    return {
        "run_id": f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "interval": interval,
        "param_snapshot": to_dict(TUNING),
        "total_signals": total_signals,
        "aggregated": overall,
        "per_symbol": {s: {"total": v["total"]} for s, v in by_symbol.items()},
    }


def write_results(result: dict, path: Path) -> None:
    """Append result to backtest_results.json (creates file if missing)."""
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = json.loads(path.read_text())
        existing["runs"].append(result)
        existing["last_updated"] = result["timestamp"]
    else:
        existing = {"version": 1, "last_updated": result["timestamp"], "runs": [result]}
    path.write_text(json.dumps(existing, indent=2, default=str))
    log.info("Wrote result to %s", path)


def _load_config(path: Path) -> dict:
    """Load backtest config YAML. Returns dict with symbols/interval/start."""
    try:
        import yaml
    except ImportError:
        log.warning("PyYAML not installed; ignoring --config %s", path)
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    cfg: dict = {}
    cfg["symbols"] = data.get("symbols") or DEFAULT_SYMBOLS
    cfg["interval"] = (data.get("intervals") or {}).get("default", DEFAULT_INTERVAL)
    tr = data.get("time_range") or {}
    cfg["start"] = tr.get("start") or DEFAULT_START
    cfg["end"] = tr.get("end") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily backtest scheduler")
    ap.add_argument("--config", type=Path, default=None,
                    help="YAML config with symbols/intervals/time_range")
    ap.add_argument("--symbols", nargs="+", default=None,
                    help=f"Symbols to backtest (overrides --config; default: {' '.join(DEFAULT_SYMBOLS)})")
    ap.add_argument("--interval", default=None,
                    help="Bar interval: 15m/1h/4h/1d/1w (default from config: 1h)")
    ap.add_argument("--start", default=None,
                    help="Start date YYYY-MM-DD (default from config: 2024-01-01)")
    ap.add_argument("--end", default=None,
                    help="End date YYYY-MM-DD (default: today)")
    ap.add_argument("--window", type=int, default=240,
                    help="Walk-forward window size in bars (default: 240 = 10d @ 1h)")
    ap.add_argument("--step", type=int, default=24,
                    help="Walk-forward step size in bars (default: 24 = 1d @ 1h)")
    ap.add_argument("--horizon", type=int, default=24,
                    help="Forward-sim horizon bars (default: 24)")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4,
                    help="Parallel worker processes (default: CPU count)")
    ap.add_argument("--min-grade", default=None, choices=["A", "B", "C(参考)"],
                    help="Only emit signals of this grade or higher")
    ap.add_argument("--snapshot", action="store_true",
                    help="Also write tuning_snapshots/ candidate YAML")
    args = ap.parse_args()

    cfg: dict = {}
    if args.config:
        cfg = _load_config(args.config)
    # Explicit CLI flags win over config; config wins over defaults.
    symbols = args.symbols or cfg.get("symbols") or DEFAULT_SYMBOLS
    interval = args.interval or cfg.get("interval") or DEFAULT_INTERVAL
    start = args.start or cfg.get("start") or DEFAULT_START
    end = args.end or cfg.get("end") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    log.info(
        "Starting backtest: symbols=%s interval=%s window=%d step=%d horizon=%d workers=%d",
        symbols, interval, args.window, args.step, args.horizon, args.workers,
    )

    result = run(
        symbols, interval, start, end,
        args.window, args.step, args.horizon, args.workers, args.min_grade,
    )

    write_results(result, RESULT_DIR / "backtest_results.json")

    if args.snapshot:
        # write_tuning_snapshot treats `root` as the *state root* and appends
        # tuning_snapshots/ itself. Passing ROOT lands candidates in the
        # repo-visible tuning_snapshots/ dir for the human PR gate.
        label = f"daily_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        snapshot_path = write_tuning_snapshot(TUNING, label, root=ROOT)
        log.info("Wrote tuning snapshot to %s", snapshot_path)

    log.info("Backtest complete: run_id=%s signals=%d",
             result["run_id"], result["total_signals"])


if __name__ == "__main__":
    main()
