"""Historical market data fetching for backtesting.

This module exposes a unified way to fetch OHLCV data over a date range.
It reuses the existing Binance direct fetcher and can be extended for other
markets (Yahoo, etc.).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from app.domain.enums import Interval, Market
from app.infra import tradingview_adapter as tv
from app.infra.marketdata import DirectBinanceCandleData
from app.infra.pyharmonics_adapter import fetch_market_data

logger = logging.getLogger(__name__)


# Map from our interval string to approximate milliseconds per candle.
_INTERVAL_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
    "1w": 7 * 24 * 60 * 60 * 1000,
}


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _fetch_tradingview_range(
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    market: str,
) -> pd.DataFrame:
    """Fetch a date range from TradingView via the bridge.

    TradingView's bridge fetches ``limit`` candles ending at ``to``.  We ask
    for enough candles to cover the requested window and then trim.
    """
    if not tv.is_tradingview_enabled() or not tv.is_bridge_healthy():
        raise RuntimeError("TradingView bridge unavailable")

    ms_per_candle = _INTERVAL_MS.get(interval)
    if ms_per_candle is None:
        raise ValueError(f"Unsupported interval for backtest: {interval}")

    end_ms = _to_ms(end)
    start_ms = _to_ms(start)
    estimated = max((end_ms - start_ms) // ms_per_candle, 1) + 1
    limit = min(estimated + 10, 5000)

    df = tv.fetch_candles(
        symbol=symbol,
        interval=interval,
        limit=limit,
        market=market,
        to=end_ms // 1000,
    )

    # Trim to requested window.
    df = df[df["open_time"] >= start_ms]
    if df.empty:
        raise RuntimeError(f"TradingView returned no data in range for {symbol}")
    return df


def fetch_historical_data(
    market: str,
    symbol: str,
    interval: str,
    lookback_days: int,
    end: Optional[datetime] = None,
) -> pd.DataFrame:
    """Fetch historical OHLCV data for a given lookback window.

    TradingView is tried first when enabled/healthy; on failure we fall back
    to Binance/Yahoo.

    Args:
        market: "binance" or "yahoo".
        symbol: Trading pair / ticker.
        interval: Candle interval (15m, 1h, 4h, 1d, 1w).
        lookback_days: Number of calendar days to look back (max 365).
        end: Optional end datetime (timezone.utc). Defaults to now.

    Returns:
        DataFrame with columns open, high, low, close, volume, dts, close_time.

    Raises:
        ValueError: For unsupported market/interval.
        RuntimeError: When data cannot be fetched.
    """
    if end is None:
        end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)

    # Try TradingView first.
    if tv.is_tradingview_enabled() and tv.is_bridge_healthy():
        try:
            df = _fetch_tradingview_range(symbol, interval, start, end, market)
            logger.info(
                "Fetched historical %s %s from TradingView (%d rows)",
                market,
                symbol,
                len(df),
            )
            return df
        except Exception as e:
            logger.warning(
                "TradingView historical fetch failed for %s/%s, falling back: %s",
                market,
                symbol,
                e,
            )

    if market == Market.BINANCE.value:
        return _fetch_binance_range(symbol, interval, start, end)

    if market == Market.YAHOO.value:
        # Yahoo data source does not yet support precise date-range backtesting.
        # Fall back to the recent-N-candles path with enough candles to cover
        # the requested window.
        return _fetch_yahoo_recent(symbol, Interval(interval), lookback_days)

    raise ValueError(f"Unsupported market for historical data: {market}")


def _fetch_binance_range(
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """Fetch Binance candles between start and end (inclusive)."""
    ms_per_candle = _INTERVAL_MS.get(interval)
    if ms_per_candle is None:
        raise ValueError(f"Unsupported interval for backtest: {interval}")

    start_ms = _to_ms(start)
    end_ms = _to_ms(end)
    estimated_candles = max((end_ms - start_ms) // ms_per_candle, 1) + 1
    # Paginate through the full requested window; the fetcher splits requests
    # into exchange-max page sizes internally.
    num_candles = min(estimated_candles, 50_000)

    fetcher = DirectBinanceCandleData()
    fetcher.get_candles(
        symbol=symbol.upper(),
        interval=interval,
        num_candles=num_candles,
        start=start_ms,
        end=end_ms,
    )
    if fetcher.df is None or fetcher.df.empty:
        raise RuntimeError(f"No historical data returned for {symbol} {interval}")
    return fetcher.df.copy()


def _fetch_yahoo_recent(
    symbol: str,
    interval: str,
    lookback_days: int,
) -> pd.DataFrame:
    """Fetch recent Yahoo candles covering approximately lookback_days."""
    candles_per_day = {
        "15m": 96,
        "1h": 24,
        "4h": 6,
        "1d": 1,
        "1w": 1,
    }.get(interval, 24)
    num_candles = int(lookback_days * candles_per_day * 1.2)
    candle_data = fetch_market_data(
        market=Market.YAHOO,
        symbol=symbol,
        interval=Interval(interval),
        candles=num_candles,
    )
    df = candle_data.df
    if df is None or df.empty:
        raise RuntimeError(f"No historical data returned for {symbol} {interval}")
    return df.copy()
