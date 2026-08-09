"""Backtest-only Binance kline loader using urllib stdlib.

The production path in ``app/infra/marketdata.py`` routes through
``curl_cffi.requests`` for TLS fingerprint impersonation. In some sandbox
environments that TLS handshake hangs (curl error 28) while a plain urllib
request returns in <1s. This module is a fallback used *only* by backtest
scripts; it does not change any production code path.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone
from typing import Optional

import pandas as pd


_INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}

# Prefer data-api.binance.vision — api.binance.com often returns HTTP 451
# from restricted networks; vision host is the public historical data API.
BINANCE_URLS = (
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.com/api/v3/klines",
    "https://api.binance.us/api/v3/klines",
)
BINANCE_URL = BINANCE_URLS[0]

_RAW_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "number_of_trades",
    "taker_buy_base_volume", "taker_buy_quote_volume", "ignore",
]


def _to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def fetch_binance_klines(
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    timeout: float = 15.0,
    max_retries: int = 3,
) -> pd.DataFrame:
    """Fetch Binance klines between ``start`` and ``end`` (inclusive), paginating.

    Returns DataFrame with columns: open, high, low, close, volume, dts, close_time.
    """
    if interval not in _INTERVAL_MS:
        raise ValueError(f"Unsupported interval: {interval}")
    start_ms = _to_ms(start)
    end_ms = _to_ms(end)
    if end_ms <= start_ms:
        raise ValueError("end must be after start")

    rows: list = []
    cursor = end_ms  # walk backwards from end
    batch_limit = 1000
    # Pick first host that answers for this symbol (sticky for pagination).
    active_base: Optional[str] = None
    while cursor > start_ms:
        params = (
            f"symbol={symbol.upper()}"
            f"&interval={interval}"
            f"&endTime={cursor}"
            f"&limit={batch_limit}"
        )
        batch = None
        last_err: Exception | None = None
        bases = (active_base,) if active_base else BINANCE_URLS
        for base in bases:
            if base is None:
                continue
            url = f"{base}?{params}"
            for attempt in range(max_retries):
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=timeout) as r:
                        batch = json.loads(r.read())
                    active_base = base
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    if attempt < max_retries - 1:
                        time.sleep(0.5 * (2 ** attempt))
            if batch is not None:
                break
        if batch is None:
            raise RuntimeError(
                f"Binance stdlib fetch failed after trying {bases}: {last_err}"
            ) from last_err
        if not batch:
            break
        first_open = batch[0][0]
        rows = batch + rows
        if first_open <= start_ms:
            break
        cursor = first_open - 1
        if len(batch) < batch_limit:
            break

    if not rows:
        raise RuntimeError(f"No Binance data for {symbol} {interval}")

    raw = pd.DataFrame(rows, columns=_RAW_COLUMNS)
    # Restrict to requested window.
    raw = raw[raw["open_time"] >= start_ms].reset_index(drop=True)
    out = pd.DataFrame({
        "open": raw["open"].astype(float),
        "high": raw["high"].astype(float),
        "low": raw["low"].astype(float),
        "close": raw["close"].astype(float),
        "volume": raw["volume"].astype(float),
        "dts": pd.to_datetime(raw["open_time"], unit="ms", utc=True),
        "close_time": (raw["close_time"] // 1000).astype("int64"),
    })
    # Set ``dts`` as index so downstream code (``df.index[end_idx]``) gets
    # timestamps, matching the production ``DirectBinanceCandleData`` shape.
    out = out.set_index("dts", drop=False)
    return out