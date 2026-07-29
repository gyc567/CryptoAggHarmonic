"""Fetch 1h OHLCV from Coinbase public candles for BTC/ETH/BNB 2024-01-01 → 2026-01-01.

Output: one CSV per symbol, columns: open_time,open,high,low,close,volume.
Resampling to 4h is done downstream in the backtest harness.
"""
from __future__ import annotations

import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

# Coinbase 1h granularity: max ~300 candles per request → ~11 day pages.
# 2 years (730 days) / 11 = ~66 pages per symbol.
GRANULARITY = 3600

# Window: 2024-01-01 00:00 UTC → 2026-01-01 00:00 UTC (730 days).
START = datetime(2024, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 1, tzinfo=timezone.utc)
START_TS = int(START.timestamp())
END_TS = int(END.timestamp())

# Stay below Coinbase's 300-row cap. 11 days × 24h = 264 rows (safe).
PAGE_HOURS = 11 * 24

SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD"]
# Note: Coinbase lists BNB-USD only from 2025-10 onward, so we substitute
# SOL-USD (same alt-L1 profile) to keep the 2-year window. Documented in the
# backtest report.
OUT_DIR = os.path.join(os.path.dirname(__file__), "data")


def fetch_one_page(symbol: str, end_iso: str, start_iso: str) -> list:
    """Fetch one page. Coinbase rejects (>300 candles) with 400 so we cap."""
    url = f"https://api.exchange.coinbase.com/products/{symbol}/candles"
    params = {"start": start_iso, "end": end_iso, "granularity": GRANULARITY}
    r = requests.get(url, params=params, timeout=15)
    if r.status_code != 200:
        return []
    return r.json()


def fetch_symbol(symbol: str) -> list:
    """Fetch the full window for one symbol, paginating backward in time.

    Coinbase returns at most 300 candles per request. Strategy: each request
    is a 11-day window. Start from END, slide backward until we cross START_TS.
    """
    rows: list = []
    end_iso = END.isoformat()
    while True:
        # The window runs from (end - 11 days) → end for the first call.
        end_dt = datetime.fromisoformat(end_iso)
        start_dt = end_dt - timedelta(hours=PAGE_HOURS)
        start_iso = max(start_dt, START).isoformat()
        chunk = fetch_one_page(symbol, end_iso, start_iso)
        if not chunk:
            break
        # Coinbase returns newest-first; rows[0] is latest, rows[-1] is oldest.
        rows.extend(chunk)
        oldest_ts = chunk[-1][0]
        if oldest_ts <= START_TS:
            break
        end_iso = datetime.fromtimestamp(oldest_ts - 1, tz=timezone.utc).isoformat()
        time.sleep(0.25)  # polite rate limit
    # Filter to window bounds and dedupe by timestamp.
    seen = set()
    unique = []
    for row in sorted(rows, key=lambda r: r[0]):  # ascending for CSV
        if row[0] in seen or row[0] < START_TS or row[0] >= END_TS:
            continue
        seen.add(row[0])
        unique.append(row)
    return unique


def save_csv(rows: list, path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time", "open", "high", "low", "close", "volume"])
        for row in rows:
            w.writerow(row)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(fetch_symbol, s): s for s in SYMBOLS}
        for fut in as_completed(futures):
            symbol = futures[fut]
            try:
                rows = fut.result()
            except Exception as e:
                print(f"{symbol}: ERROR {e}")
                continue
            out = os.path.join(OUT_DIR, f"{symbol.lower().replace('-', '')}_1h.csv")
            save_csv(rows, out)
            print(f"{symbol}: {len(rows)} hourly rows → {out}")


if __name__ == "__main__":
    main()
