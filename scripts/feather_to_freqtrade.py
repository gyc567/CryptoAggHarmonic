#!/usr/bin/env python3
"""
feather_to_freqtrade.py

Convert feather files from fq-data-downloader into Freqtrade-compatible
CSV files (user_data/data/{exchange}/{pair}-{timeframe}.csv).

Usage:
    python scripts/feather_to_freqtrade.py [--feather-dir PATH] [--out-dir PATH] [--dry-run]

 feather-dir  : directory containing *.feather files (default: fq-data-downloader/data/binance)
 out-dir      : freqtrade user_data/data directory (default: freqtrade_dev_mcp/user_data/data)
 dry-run      : print conversions without writing files
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("feather_to_freqtrade")

# ---------------------------------------------------------------------------
# Mapping from feather filename pattern → freqtrade pair-timeframe label
# ---------------------------------------------------------------------------
FEATHER_SPECS: dict[str, tuple[str, str]] = {
    # symbol       pair-with-underscore   timeframe
    "BTC_USDT-1h":  ("BTC_USDT",   "1h"),
    "BTC_USDT-4h":  ("BTC_USDT",   "4h"),
    "BTC_USDT-1d":  ("BTC_USDT",   "1d"),
    "ETH_USDT-1h":  ("ETH_USDT",   "1h"),
    "ETH_USDT-4h":  ("ETH_USDT",   "4h"),
    "ETH_USDT-1d":  ("ETH_USDT",   "1d"),
    "SOL_USDT-1h":  ("SOL_USDT",   "1h"),
    "SOL_USDT-4h":  ("SOL_USDT",   "4h"),
    "SOL_USDT-1d":  ("SOL_USDT",   "1d"),
    "BNB_USDT-1h":  ("BNB_USDT",   "1h"),
    "BNB_USDT-4h":  ("BNB_USDT",   "4h"),
    "BNB_USDT-1d":  ("BNB_USDT",   "1d"),
}

# Freqtrade CSV column names (open time in ms)
CSV_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "buy_volume",
    "ignore",
]


def ms_to_s(ms: int) -> int:
    """Convert millisecond epoch → second epoch."""
    return ms // 1000


def feather_to_freqtrade_csv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform a feather DataFrame (columns: timestamp, open, high, low, close, volume)
    into a freqtrade-compatible CSV DataFrame.

    The feather 'timestamp' column holds the bar open time in milliseconds UTC.
    """
    # Feather data may arrive newest-first; caller is responsible for sorting.
    open_ts = df["timestamp"].apply(ms_to_s)
    if len(df) >= 2:
        period_ms = int(df["timestamp"].iloc[1]) - int(df["timestamp"].iloc[0])
    else:
        period_ms = 3_600_000

    records: dict[str, list] = {
        "open_time":    open_ts.tolist(),
        "open":         df["open"].astype(float).tolist(),
        "high":         df["high"].astype(float).tolist(),
        "low":          df["low"].astype(float).tolist(),
        "close":        df["close"].astype(float).tolist(),
        "volume":       df["volume"].astype(float).tolist(),
        "close_time":   (open_ts + (period_ms // 1000) - 1).tolist(),
        "quote_volume": [0.0] * len(df),
        "trades":       [0] * len(df),
        "buy_volume":   [0.0] * len(df),
        "ignore":       [""] * len(df),
    }
    return pd.DataFrame(records, columns=CSV_COLUMNS)


def convert_file(
    feather_path: Path,
    out_dir: Path,
    dry_run: bool = False,
) -> Path | None:
    """Convert a single feather file and return the output CSV path (or None on skip)."""
    stem = feather_path.stem  # e.g. "BTC_USDT-1h"
    if stem not in FEATHER_SPECS:
        log.warning("Skipping unknown file pattern: %s (not in FEATHER_SPECS)", stem)
        return None

    pair, timeframe = FEATHER_SPECS[stem]
    exchange_dir = out_dir / "binance"
    out_path = exchange_dir / f"{pair}-{timeframe}.csv"

    log.info("Reading: %s", feather_path)
    try:
        df = pd.read_feather(str(feather_path))
    except Exception as exc:
        log.error("Failed to read feather %s: %s", feather_path, exc)
        return None

    if df.empty:
        log.warning("Feather file %s is empty — skipping", feather_path)
        return None

    # Sort ascending (data may be newest-first)
    df = df.sort_values("timestamp").reset_index(drop=True)

    n_rows = len(df)
    dt_start = pd.to_datetime(df["timestamp"].iloc[0], unit="ms", utc=True)
    dt_end   = pd.to_datetime(df["timestamp"].iloc[-1], unit="ms", utc=True)
    log.info(
        "  %d rows  |  %s  →  %s  |  pair=%s  tf=%s",
        n_rows, dt_start.strftime("%Y-%m-%d"), dt_end.strftime("%Y-%m-%d"),
        pair, timeframe,
    )

    ft_df = feather_to_freqtrade_csv(df)

    if dry_run:
        log.info("  [DRY RUN] Would write %s rows to %s", len(ft_df), out_path)
        return out_path

    exchange_dir.mkdir(parents=True, exist_ok=True)
    ft_df.to_csv(out_path, index=False)
    log.info("  Wrote: %s  (%.1f KB)", out_path, out_path.stat().st_size / 1024)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert feather files to freqtrade CSVs")
    parser.add_argument(
        "--feather-dir",
        type=Path,
        default=Path("/Users/jie/code/fq-data-downloader/data/binance"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/Users/jie/code/CryptoAggHarmonic/freqtrade_dev_mcp/user_data/data"),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print conversions without writing files",
    )
    args = parser.parse_args()

    if not args.feather_dir.exists():
        log.error("Feather directory not found: %s", args.feather_dir)
        return

    feather_files = sorted(args.feather_dir.glob("*.feather"))
    if not feather_files:
        log.warning("No .feather files found in %s", args.feather_dir)
        return

    log.info("Found %d feather file(s) in %s", len(feather_files), args.feather_dir)
    if args.dry_run:
        log.info("DRY RUN — no files will be written\n")

    converted = 0
    for fp in feather_files:
        if convert_file(fp, args.out_dir, dry_run=args.dry_run):
            converted += 1

    log.info("\nDone.  Converted %d / %d file(s).", converted, len(feather_files))
    if not args.dry_run:
        log.info(
            "Freqtrade data dir: %s",
            args.out_dir / "binance",
        )


if __name__ == "__main__":
    main()
