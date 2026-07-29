"""TradingView data adapter via the Node.js bridge service.

This module lets the Python backend use TradingView as a primary market-data
source while keeping all Node/WS code isolated in ``tradingview-bridge/``.

The bridge URL is configurable via ``TRADINGVIEW_BRIDGE_URL`` (default:
``http://127.0.0.1:5002``).  Set ``USE_TRADINGVIEW=false`` to disable the
adapter and fall back to Binance/Yahoo.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

import pandas as pd
import requests

from app.api.errors import AppError
from app.domain.enums import ErrorCode

logger = logging.getLogger(__name__)

DEFAULT_BRIDGE_URL = "http://127.0.0.1:5002"
REQUEST_TIMEOUT = 8

# Sliding-window cache for ``is_bridge_healthy``. The bridge health endpoint
# is a synchronous WebSocket-state probe; calling it on every analyzer tick
# would hammer the bridge. We treat the result as fresh for ``HEALTH_CACHE_TTL``
# seconds and re-probe on miss. Tests reset this with ``reset_health_cache``.
HEALTH_CACHE_TTL = float(os.getenv("TRADINGVIEW_HEALTH_CACHE_TTL", "5"))

# Standard columns expected by downstream consumers (matches pyharmonics CandleData.COLUMNS).
COLUMNS = ["open", "high", "low", "close", "volume", "close_time", "dts"]


def get_bridge_url() -> str:
    return os.getenv("TRADINGVIEW_BRIDGE_URL", DEFAULT_BRIDGE_URL).rstrip("/")


def is_tradingview_enabled() -> bool:
    return os.getenv("USE_TRADINGVIEW", "true").lower() not in ("0", "false", "no")


# --- Health cache ------------------------------------------------------------
#
# ``_HEALTH_CACHE`` is guarded by ``_HEALTH_LOCK`` so concurrent analyzer
# workers don't all probe the bridge when the cache expires simultaneously.
_health_lock = threading.Lock()
_health_cache: dict = {
    "expires_at": 0.0,  # monotonic seconds; 0.0 -> forced miss on first call.
    "value": False,
}


def reset_health_cache() -> None:
    """Drop the cached health result. Used by tests; harmless in prod."""
    with _health_lock:
        _health_cache["expires_at"] = 0.0
        _health_cache["value"] = False


def _probe_bridge_health() -> bool:
    """Synchronous health probe with no caching. Returns True iff bridge up + TV connected."""
    try:
        resp = requests.get(
            f"{get_bridge_url()}/health",
            timeout=2,
        )
        if resp.status_code != 200:
            return False
        data = resp.json()
        return data.get("status") == "ok" and data.get("connected") is True
    except Exception as e:
        logger.debug("TradingView bridge health check failed: %s", e)
        return False


def is_bridge_healthy() -> bool:
    """Return True if the TradingView bridge is up AND connected to TV.

    Result is cached for :data:`HEALTH_CACHE_TTL` seconds. Probe failures
    are cached too — only the next call after TTL expiry will retry.
    """
    with _health_lock:
        now = time.monotonic()
        if now < _health_cache["expires_at"]:
            return _health_cache["value"]
        # Probe inside the lock so concurrent callers don't all hit the
        # bridge on the same miss; the slow-path cost is bounded by the
        # 2-second HTTP timeout on ``_probe_bridge_health``.
        value = _probe_bridge_health()
        _health_cache["value"] = value
        _health_cache["expires_at"] = now + HEALTH_CACHE_TTL
        return value


def _map_market(market: str) -> str:
    """Map internal market names to TradingView exchange prefixes."""
    market = market.lower()
    if market == "binance":
        return "BINANCE"
    if market == "yahoo":
        # Yahoo symbols in TV are often on NASDAQ/NYSE/OTC; try prefixing
        # with the default US exchange and let the bridge resolve.
        return "TVC"
    return market.upper()


def fetch_candles(
    symbol: str,
    interval: str,
    limit: int = 500,
    market: str = "binance",
    to: Optional[int] = None,
) -> pd.DataFrame:
    """Fetch OHLCV candles from TradingView.

    Args:
        symbol: Trading pair / ticker (e.g. BTCUSDT, AAPL).
        interval: Candle interval (1m, 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1w).
        limit: Number of candles to fetch (max 5000).
        market: Market/exchange identifier.
        to: Optional Unix timestamp (seconds) to fetch backwards from.

    Returns:
        DataFrame with columns open_time, open, high, low, close, volume,
        close_time, dts.

    Raises:
        AppError: If TradingView is disabled, the bridge is down, or data
        cannot be retrieved.
    """
    if not is_tradingview_enabled():
        raise AppError(
            ErrorCode.MARKET_DATA_UNAVAILABLE,
            "TradingView adapter is disabled",
            retryable=True,
        )

    params: dict[str, Any] = {
        "symbol": symbol.upper(),
        "market": _map_market(market),
        "interval": interval,
        "limit": min(limit, 5000),
    }
    if to is not None:
        params["to"] = int(to)

    try:
        resp = requests.get(
            f"{get_bridge_url()}/candles",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as e:
        logger.exception("TradingView bridge request failed")
        raise AppError(
            ErrorCode.MARKET_DATA_UNAVAILABLE,
            f"TradingView bridge unreachable: {e}",
            retryable=True,
        ) from e

    if not payload.get("success"):
        error = payload.get("error", "unknown TradingView error")
        raise AppError(
            ErrorCode.MARKET_DATA_UNAVAILABLE,
            f"TradingView data error: {error}",
            retryable=True,
        )

    candles = payload.get("candles")
    if not candles:
        raise AppError(
            ErrorCode.MARKET_DATA_UNAVAILABLE,
            f"TradingView returned no candles for {symbol} {interval}",
            retryable=True,
        )

    df = pd.DataFrame(candles)
    # Ensure column order and types match downstream expectations.
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["close_time"] = pd.to_numeric(df["close_time"], errors="coerce").astype("int64")
    df["dts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)

    # Drop open_time to keep the same schema as pyharmonics CandleData.COLUMNS.
    df = df.drop(columns=["open_time"], errors="ignore")

    return df[COLUMNS].copy()


def fetch_market_data(
    market: str,
    symbol: str,
    interval: str,
    candles: int = 500,
) -> Any:
    """Return a CandleData-compatible object for pyharmonics-style consumers.

    This is the TradingView equivalent of ``DirectBinanceCandleData``.
    """
    # Local import to avoid circular dependencies.
    from pyharmonics.marketdata.candle_base import CandleData

    class TradingViewCandleData(CandleData):
        SOURCE = "TradingView"

        def get_candles(
            self,
            symbol: str,
            interval: str,
            num_candles: Optional[int] = None,
        ) -> None:
            self.symbol = symbol
            self.interval = interval
            self.num_candles = num_candles or 500
            self.df = fetch_candles(
                symbol=symbol,
                interval=interval,
                limit=self.num_candles,
                market=market,
            )
            self.reset_index()

    cd = TradingViewCandleData()
    cd.get_candles(symbol, interval, candles)
    return cd
