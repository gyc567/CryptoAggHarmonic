"""Public market data fetchers used as fallbacks for pyharmonics.

These adapters call public REST endpoints directly so the analysis pipeline can
keep working when the upstream `pyharmonics` connectors fail (e.g. due to
network, library or rate-limit issues).
"""
import logging
import os
from typing import Optional

import pandas as pd
import requests
from pyharmonics.marketdata.candle_base import CandleData

logger = logging.getLogger(__name__)


class DirectBinanceCandleData(CandleData):
    """Fetch Binance spot klines directly from the public REST API.

    Returns a CandleData-compatible object with ``df``, ``symbol`` and
    ``interval`` attributes.
    """

    MAX_CANDLES = 1000
    SOURCE = "BinanceDirect"
    INTERVALS = {
        CandleData.MIN_1: "1m",
        CandleData.MIN_3: "3m",
        CandleData.MIN_5: "5m",
        CandleData.MIN_15: "15m",
        CandleData.MIN_30: "30m",
        CandleData.MIN_45: "45m",
        CandleData.HOUR_1: "1h",
        CandleData.HOUR_2: "2h",
        CandleData.HOUR_4: "4h",
        CandleData.HOUR_8: "8h",
        CandleData.DAY_1: "1d",
        CandleData.DAY_3: "3d",
        CandleData.DAY_5: "5d",
        CandleData.WEEK_1: "1w",
        CandleData.MONTH_1: "1M",
    }

    # ``api.binance.com`` is geo-blocked in some regions (e.g. returns HTTP 451).
    # Allow operators to point at an accessible mirror such as ``https://api.binance.us``.
    BASE_URL = os.getenv("BINANCE_API_BASE_URL", "https://api.binance.com")

    def __init__(
        self,
        schema: Optional[list] = None,
        time_zone: str = "UTC",
        df_index: str = CandleData.DTS,
    ):
        if schema is None:
            self.schema = [
                {"name": "open_time", "type": "int64"},
                {"name": self.OPEN, "type": "float"},
                {"name": self.HIGH, "type": "float"},
                {"name": self.LOW, "type": "float"},
                {"name": self.CLOSE, "type": "float"},
                {"name": self.VOLUME, "type": "float"},
                {"name": self.CLOSE_TIME, "type": "int64"},
                {"name": "quote_asset_volume", "type": "float"},
                {"name": "number_of_trades", "type": "int64"},
                {"name": "taker_buy_base_volume", "type": "float"},
                {"name": "taker_buy_quote_volume", "type": "float"},
                {"name": "ignore", "type": "float"},
            ]
        self.columns = [c["name"] for c in self.schema]
        self.time_zone = time_zone
        self.df = None
        self.candle_gap = None
        if df_index in (self.DTS, self.CLOSE_TIME):
            self.df_index = df_index
        else:
            raise ValueError(f'df_index must be one of "{self.DTS}" or "{self.CLOSE_TIME}"')

    def get_candles(
        self,
        symbol: str,
        interval: str,
        num_candles: Optional[int] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> None:
        """Fetch candles from Binance public API and populate self.df."""
        if interval not in self.INTERVALS:
            from pyharmonics.marketdata.candle_base import InvalidTimeframe

            raise InvalidTimeframe(
                f"Binance intervals must be one of {list(self.INTERVALS.values())}"
            )

        self.symbol = symbol
        self.interval = interval
        self.num_candles = num_candles or self.MAX_CANDLES
        self.start = start
        self.end = end

        binance_interval = self.INTERVALS[interval]

        url = f"{self.BASE_URL}/api/v3/klines"
        try:
            rows = self._fetch_paginated(url, symbol.upper(), binance_interval, self.num_candles)
        except Exception as e:
            logger.exception("Binance direct API request failed for %s", symbol)
            raise RuntimeError(f"Binance API request failed: {e}") from e

        if not rows:
            raise RuntimeError(f"Binance returned no data for {symbol}")

        rows = rows[-self.num_candles:]

        self.df = self._to_dataframe(rows)
        self.reset_index()

    def _fetch_paginated(
        self,
        url: str,
        symbol: str,
        interval: str,
        num_candles: int,
    ) -> list:
        """Fetch up to ``num_candles`` klines, paginating backwards in time.

        Binance returns at most ``MAX_CANDLES`` rows per request. When more are
        requested, walk backwards using ``endTime`` so the final result is the
        most recent ``num_candles`` candles (ascending by open time).

        If ``self.start`` or ``self.end`` are set, they act as absolute bounds
        (inclusive, milliseconds) and ``num_candles`` becomes a safety cap.
        """
        collected: list = []
        end_time: Optional[int] = self.end
        start_time: Optional[int] = self.start

        while len(collected) < num_candles:
            batch_size = min(num_candles - len(collected), self.MAX_CANDLES)
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": batch_size,
            }
            if end_time is not None:
                params["endTime"] = end_time

            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            batch = resp.json()

            if not batch:
                break

            # Filter out candles before the requested start bound.
            if start_time is not None:
                batch = [row for row in batch if row[0] >= start_time]
                if not batch:
                    break

            collected = batch + collected
            if len(batch) < batch_size:
                # Exchange has no earlier data.
                break
            end_time = batch[0][0] - 1
            if start_time is not None and end_time < start_time:
                break

        return collected

    def _to_dataframe(self, rows: list) -> pd.DataFrame:
        df = pd.DataFrame(data=rows, columns=self.columns)
        for col in self.schema:
            df[col["name"]] = df[col["name"]].astype(col["type"])

        # Binance returns milliseconds
        df[self.CLOSE_TIME] = (df[self.CLOSE_TIME] // 1000).astype("int64")
        df[self.DTS] = pd.to_datetime(df[self.CLOSE_TIME], unit="s", utc=True).dt.tz_convert(
            self.time_zone
        )
        return df[self.COLUMNS]
