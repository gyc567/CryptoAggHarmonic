#!/usr/bin/env python3
"""Backtest data download and cache manager.

Downloads K-line data from Binance and caches it locally as Parquet files
for use by backtest scripts. Avoids repeated API calls during development.

Usage:
    python scripts/download_backtest_data.py                    # download BTCUSDT 4h
    python scripts/download_backtest_data.py --status          # show cache status
    python scripts/download_backtest_data.py --clean           # delete all cache
    python scripts/download_backtest_data.py --symbol ETHUSDT --interval 1h
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Make app.* importable when invoked from repo root without install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

# Reuse the reliable stdlib implementation.
from scripts._binance_stdlib import fetch_binance_klines

# Default data root: data/backtest/
DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "backtest"

# Fixed end date for reproducible backtests (monthly update recommended).
FIXED_END_DATE = datetime(2026, 8, 1, tzinfo=timezone.utc)

# Default lookback: 730 days (~2 years, covers full market cycle).
DEFAULT_DAYS = 730

# Supported symbols and intervals for quick download.
SUPPORTED_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
SUPPORTED_INTERVALS = ["15m", "1h", "4h", "1d"]


def get_data_path(
    symbol: str,
    interval: str,
    exchange: str = "binance",
    root: Path | None = None,
) -> Path:
    """Return path to the Parquet data file.

    Path: {root}/{exchange}/{symbol}/{interval}.parquet
    """
    root = root or DATA_ROOT
    return root / exchange / symbol / f"{interval}.parquet"


def get_meta_path(
    symbol: str,
    interval: str,
    exchange: str = "binance",
    root: Path | None = None,
) -> Path:
    """Return path to the JSON metadata file."""
    root = root or DATA_ROOT
    return root / exchange / symbol / f"{interval}.meta.json"


def load_cached(
    symbol: str,
    interval: str,
    exchange: str = "binance",
    root: Path | None = None,
) -> pd.DataFrame | None:
    """Load data from local cache. Returns None if not cached or corrupted."""
    path = get_data_path(symbol, interval, exchange, root)
    if path.exists():
        try:
            return pd.read_parquet(path)
        except Exception:
            # File corrupted, remove and return None
            try:
                path.unlink()
            except Exception:
                pass
            return None
    return None


def save_data(
    df: pd.DataFrame,
    symbol: str,
    interval: str,
    exchange: str = "binance",
    root: Path | None = None,
) -> Path:
    """Save DataFrame to Parquet with metadata.

    Returns the path to the saved file.
    """
    data_path = get_data_path(symbol, interval, exchange, root)
    data_path.parent.mkdir(parents=True, exist_ok=True)

    # Save Parquet with index (dts column).
    df.to_parquet(data_path, index=True)

    # Save metadata.
    meta = {
        "symbol": symbol,
        "interval": interval,
        "exchange": exchange,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "date_range": {
            "start": df.index[0].isoformat() if len(df) > 0 else None,
            "end": df.index[-1].isoformat() if len(df) > 0 else None,
        },
        "candles": len(df),
        "source": "binance_stdlib",
        "version": "v1",
    }
    meta_path = get_meta_path(symbol, interval, exchange, root)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    return data_path


def validate_data(df: pd.DataFrame) -> bool:
    """Validate data integrity. Returns True if valid."""
    if df is None or df.empty:
        return False
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        return False
    if not df.index.is_monotonic_increasing:
        return False
    if (df["high"] < df["low"]).any():
        return False
    if (df["close"] <= 0).any():
        return False
    return True


def download_data(
    symbol: str,
    interval: str,
    days: int = DEFAULT_DAYS,
    exchange: str = "binance",
    root: Path | None = None,
    max_retries: int = 3,
    verbose: bool = True,
) -> pd.DataFrame:
    """Download K-line data from Binance and cache locally.

    Args:
        symbol: Trading pair (e.g. "BTCUSDT").
        interval: Candle interval (e.g. "4h").
        days: Number of calendar days to look back.
        exchange: Exchange name (default: binance).
        root: Override data root path.
        max_retries: Number of retry attempts on failure.
        verbose: Print progress messages.

    Returns:
        DataFrame with columns: open, high, low, close, volume, dts, close_time.
    """
    if interval not in SUPPORTED_INTERVALS:
        raise ValueError(f"Unsupported interval: {interval}. Use one of {SUPPORTED_INTERVALS}")

    start = FIXED_END_DATE - timedelta(days=days)
    end = FIXED_END_DATE

    if verbose:
        print(f"[download] {symbol} {interval} ({days}d: {start.date()} -> {end.date()})")

    # Fetch with retry.
    last_err: Exception | None = None
    df = None
    for attempt in range(max_retries):
        try:
            df = fetch_binance_klines(symbol, interval, start, end)
            last_err = None  # Clear error on success
            break
        except Exception as e:
            last_err = e
            if verbose:
                print(f"[download] attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff.

    if last_err is not None or df is None:
        raise RuntimeError(f"Failed to download {symbol} {interval} after {max_retries} attempts") from last_err

    if not validate_data(df):
        raise ValueError(f"Downloaded data failed validation for {symbol} {interval}")

    # Cache to disk.
    path = save_data(df, symbol, interval, exchange, root)

    if verbose:
        print(f"[download] saved {len(df)} candles to {path}")

    return df


def ensure_data(
    symbol: str,
    interval: str,
    days: int = DEFAULT_DAYS,
    exchange: str = "binance",
    root: Path | None = None,
    verbose: bool = True,
) -> tuple[pd.DataFrame, bool]:
    """Load from cache if available, otherwise download.

    Returns:
        Tuple of (DataFrame, was_cached) where was_cached indicates if loaded from cache.
    """
    root = root or DATA_ROOT
    df = load_cached(symbol, interval, exchange, root)
    if df is not None:
        if verbose:
            path = get_data_path(symbol, interval, exchange, root)
            print(f"[cache] loaded {len(df)} candles from {path}")
        return df, True

    df = download_data(symbol, interval, days, exchange, root, verbose=verbose)
    return df, False


def get_cache_status(
    symbol: str | None = None,
    interval: str | None = None,
    root: Path | None = None,
) -> dict:
    """Get cache status for specified symbol/interval or all."""
    root = root or DATA_ROOT
    results = []

    symbols = [symbol] if symbol else SUPPORTED_SYMBOLS
    intervals = [interval] if interval else SUPPORTED_INTERVALS

    for sym in symbols:
        for iv in intervals:
            data_path = get_data_path(sym, iv, root=root)
            meta_path = get_meta_path(sym, iv, root=root)

            entry = {
                "symbol": sym,
                "interval": iv,
                "cached": data_path.exists(),
                "data_path": str(data_path),
            }

            if meta_path.exists():
                try:
                    entry["meta"] = json.loads(meta_path.read_text())
                except Exception:
                    entry["meta"] = None

            results.append(entry)

    return {"entries": results, "root": str(root)}


def clean_cache(
    symbol: str | None = None,
    interval: str | None = None,
    root: Path | None = None,
    verbose: bool = True,
) -> int:
    """Delete cached data files.

    Returns the number of files deleted.
    """
    root = root or DATA_ROOT
    symbols = [symbol] if symbol else SUPPORTED_SYMBOLS
    intervals = [interval] if interval else SUPPORTED_INTERVALS

    deleted = 0
    for sym in symbols:
        for iv in intervals:
            data_path = get_data_path(sym, iv, root=root)
            meta_path = get_meta_path(sym, iv, root=root)

            for path in (data_path, meta_path):
                if path.exists():
                    path.unlink()
                    deleted += 1
                    if verbose:
                        print(f"[clean] deleted {path}")

    return deleted


# --- CLI -----------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT", choices=SUPPORTED_SYMBOLS,
        help="Trading pair (default: BTCUSDT)")
    parser.add_argument("--interval", default="4h", choices=SUPPORTED_INTERVALS,
        help="Candle interval (default: 4h)")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
        help=f"Days to look back (default: {DEFAULT_DAYS})")
    parser.add_argument("--root", type=Path, default=None,
        help=f"Override data root (default: {DATA_ROOT})")
    parser.add_argument("--force", action="store_true",
        help="Force re-download even if cache exists")
    parser.add_argument("--status", action="store_true",
        help="Show cache status and exit")
    parser.add_argument("--clean", action="store_true",
        help="Delete cached data and exit")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true",
        help="Download all supported symbol/interval combinations")
    group.add_argument("--batch", nargs="+",
        help="Download specific symbol:interval pairs, e.g. --batch BTCUSDT:4h ETHUSDT:1h")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = args.root or DATA_ROOT

    if args.status:
        status = get_cache_status(root=root)
        print(f"Cache root: {status['root']}\n")
        for entry in status["entries"]:
            cached = "✓" if entry["cached"] else "✗"
            meta = entry.get("meta")
            if meta:
                info = f"{meta['candles']} candles, {meta['downloaded_at'][:10]}"
            else:
                info = "not cached"
            print(f"  {cached} {entry['symbol']:10} {entry['interval']:4}  {info}")
        return 0

    if args.clean:
        deleted = clean_cache(root=root)
        print(f"[clean] deleted {deleted} file(s)")
        return 0

    if args.all:
        # Download all combinations.
        for sym in SUPPORTED_SYMBOLS:
            for iv in SUPPORTED_INTERVALS:
                try:
                    ensure_data(sym, iv, args.days, root=root)
                except Exception as e:
                    print(f"[error] {sym} {iv}: {e}")
        return 0

    if args.batch:
        for pair in args.batch:
            if ":" not in pair:
                print(f"[error] Invalid pair format: {pair}, use SYMBOL:INTERVAL")
                continue
            sym, iv = pair.split(":", 1)
            if sym not in SUPPORTED_SYMBOLS:
                print(f"[error] Unsupported symbol: {sym}, use one of {SUPPORTED_SYMBOLS}")
                continue
            if iv not in SUPPORTED_INTERVALS:
                print(f"[error] Unsupported interval: {iv}, use one of {SUPPORTED_INTERVALS}")
                continue
            try:
                ensure_data(sym, iv, args.days, root=root)
            except Exception as e:
                print(f"[error] {sym} {iv}: {e}")
        return 0

    # Default: single symbol/interval.
    symbol = args.symbol
    interval = args.interval

    if args.force:
        clean_cache(symbol, interval, root=root, verbose=False)
        df = download_data(symbol, interval, args.days, root=root, verbose=True)
    else:
        df, was_cached = ensure_data(symbol, interval, args.days, root=root, verbose=True)
        if was_cached:
            print(f"[hint] Use --force to re-download")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
