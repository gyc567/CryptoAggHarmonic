"""Binance USDT-M Futures data source using REST API."""
import logging
import os
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Configurable endpoints via environment variables
_FUTURES_REST_BASE = os.getenv("BINANCE_FUTURES_REST_URL", "https://fapi.binance.com")
_WS_URL = os.getenv("BINANCE_WS_URL", "wss://fstream.binance.com/ws")


class FuturesCandleData:
    """
    永续合约K线数据容器，实现与 pyharmonics.BinanceCandleData 兼容的接口。

    detect_patterns() 需要:
        candle_data.df        — pandas DataFrame
        candle_data.symbol    — 交易对
        candle_data.interval  — K线周期
    """

    # pyharmonics 列名常量
    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"
    CLOSE_TIME = "close_time"
    DTS = "dts"  # datetime index column

    def __init__(self, symbol: str, interval: str, df: pd.DataFrame):
        self.symbol = symbol
        self.interval = interval
        self.df = df

        # 确保 dts 列存在（pyharmonics 需要）
        if self.DTS not in df.columns and "open_time" in df.columns:
            self.df = self.df.set_index(pd.to_datetime(self.df["open_time"], unit="ms"))
            self.df.index.name = self.DTS

    @property
    def websocket_url(self) -> str:
        """客户端直连 Binance WebSocket 的 URL"""
        return f"{_WS_URL}/{self.symbol.lower()}@kline_{self.interval}"


class FuturesDataSource:
    """
    Binance USDT-M 永续合约数据源。

    使用 REST 接口获取历史K线，并生成客户端直连 Binance WebSocket 的 URL。
    不持有 WebSocket 连接（方案A：客户端直连）。
    """

    def __init__(self, symbol: str, interval: str):
        """
        Args:
            symbol: 合约交易对，如 "BTCUSDT"
            interval: K线周期，如 "1m", "5m", "15m", "1h", "4h", "1d"
        """
        self.symbol = symbol.upper().strip()
        self.interval = interval.lower().strip()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "pyharmonics-gpt/1.0",
            "Accept": "application/json",
        })

    @property
    def websocket_url(self) -> str:
        """
        返回客户端直连 Binance 的 WebSocket URL。
        格式: <symbol>@kline_<interval>
        """
        return f"{_WS_URL}/{self.symbol.lower()}@kline_{self.interval}"

    def get_candles(self, limit: int = 100) -> FuturesCandleData:
        """
        获取历史K线（REST 主链路），返回与 pyharmonics 兼容的数据容器。

        Args:
            limit: K线数量，1-1500，默认100

        Returns:
            FuturesCandleData（拥有 .df, .symbol, .interval 属性）

        Raises:
            requests.HTTPError: API 返回错误状态码
        """
        url = f"{_FUTURES_REST_BASE}/fapi/v1/klines"
        params = {
            "symbol": self.symbol,
            "interval": self.interval,
            "limit": limit,
        }

        response = self._session.get(url, params=params, timeout=10)
        response.raise_for_status()

        raw = response.json()
        rows = [self._parse_rest_kline(k) for k in raw]

        df = pd.DataFrame(rows)
        return FuturesCandleData(symbol=self.symbol, interval=self.interval, df=df)

    def _parse_rest_kline(self, k: list) -> dict:
        """
        解析 REST K线格式为 dict。

        Binance /fapi/v1/klines 返回:
        [open_time, open, high, low, close, volume, close_time,
         quote_volume, trades, taker_base, taker_quote, ignore]
        """
        return {
            "open_time": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": int(k[6]),
        }

    def get_latest_close_time(self) -> Optional[int]:
        """获取最新一根K线的收盘时间（毫秒）"""
        data = self.get_candles(limit=1)
        if data.df.empty:
            return None
        return int(data.df["close_time"].iloc[-1])

    def __del__(self):
        if hasattr(self, "_session"):
            self._session.close()
