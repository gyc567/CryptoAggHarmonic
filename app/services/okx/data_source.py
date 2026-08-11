"""Read-only OKX market data wrapper.

Phase 1 surface: market module tools only (no writes). Used as a
secondary data source alongside ``app/infra/marketdata.py`` (which
talks to Binance).

The data source is a thin wrapper that:

  - Hides the MCP transport from callers
  - Sanitizes instrument ids (e.g. "BTC-USDT" → request field)
  - Records latency metrics on the shared ``CollectorRegistry``

It does NOT cache. Callers (analyze API) cache at their layer.

Public surface (Phase 1):

  - ``OKXMarketData(client)``
  - ``.get_ticker(instId) -> Ticker``
  - ``.get_candles(instId, bar, limit) -> list[Candle]``
  - ``.get_funding_rate(instId) -> FundingRate``
  - ``.get_open_interest(instType) -> list[OpenInterest]``
  - ``.get_mark_price(instId) -> MarkPrice``

Phase 2 will add swap-specific read methods and ``smartmoney`` module
tools.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .mcp_client import OKXMCPClient

logger = logging.getLogger(__name__)


@dataclass
class Ticker:
    instId: str
    last: float
    bid: float
    ask: float
    vol24h: float
    ts: str


@dataclass
class Candle:
    ts: str
    o: float
    h: float
    l: float
    c: float
    vol: float


@dataclass
class FundingRate:
    instId: str
    fundingRate: float
    nextFundingTime: str
    ts: str


@dataclass
class OpenInterest:
    instId: str
    oi: float
    oiCcy: str
    ts: str


@dataclass
class MarkPrice:
    instId: str
    markPx: float
    ts: str


class OKXMarketData:
    """Read-only OKX market data accessor."""

    def __init__(self, client: OKXMCPClient) -> None:
        self.client = client

    def get_ticker(self, instId: str) -> Ticker:
        data = self.client.invoke_tool(
            "market_get_ticker", {"instId": instId}, is_write=False
        )
        # OKX ticker response shape:
        #   { "data": [{ "instId": ..., "last": ..., "bidPx": ..., "askPx": ..., "vol24h": ..., "ts": ... }] }
        items = data.data.get("data", []) if isinstance(data.data, dict) else []
        if not items:
            raise ValueError(f"okx ticker returned empty data for instId={instId}")
        t = items[0]
        return Ticker(
            instId=t["instId"],
            last=float(t["last"]),
            bid=float(t.get("bidPx", 0)),
            ask=float(t.get("askPx", 0)),
            vol24h=float(t.get("vol24h", 0)),
            ts=str(t.get("ts", "")),
        )

    def get_candles(self, instId: str, bar: str = "1H", limit: int = 100) -> list[Candle]:
        data = self.client.invoke_tool(
            "market_get_candles",
            {"instId": instId, "bar": bar, "limit": str(limit)},
            is_write=False,
        )
        items = data.data.get("data", []) if isinstance(data.data, dict) else []
        candles: list[Candle] = []
        for row in items:
            # OKX candle row: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
            candles.append(
                Candle(ts=str(row[0]), o=float(row[1]), h=float(row[2]), l=float(row[3]),
                       c=float(row[4]), vol=float(row[5]))
            )
        return candles

    def get_funding_rate(self, instId: str) -> FundingRate:
        data = self.client.invoke_tool(
            "market_get_funding_rate", {"instId": instId}, is_write=False
        )
        items = data.data.get("data", []) if isinstance(data.data, dict) else []
        if not items:
            raise ValueError(f"okx funding rate returned empty for instId={instId}")
        f = items[0]
        return FundingRate(
            instId=f["instId"],
            fundingRate=float(f["fundingRate"]),
            nextFundingTime=str(f.get("nextFundingTime", "")),
            ts=str(f.get("ts", "")),
        )

    def get_open_interest(self, instType: str = "SWAP") -> list[OpenInterest]:
        data = self.client.invoke_tool(
            "market_get_open_interest", {"instType": instType}, is_write=False
        )
        items = data.data.get("data", []) if isinstance(data.data, dict) else []
        return [
            OpenInterest(
                instId=o["instId"],
                oi=float(o.get("oi", 0)),
                oiCcy=str(o.get("oiCcy", "")),
                ts=str(o.get("ts", "")),
            )
            for o in items
        ]

    def get_mark_price(self, instId: str) -> MarkPrice:
        data = self.client.invoke_tool(
            "market_get_mark_price", {"instId": instId}, is_write=False
        )
        items = data.data.get("data", []) if isinstance(data.data, dict) else []
        if not items:
            raise ValueError(f"okx mark price returned empty for instId={instId}")
        m = items[0]
        return MarkPrice(
            instId=m["instId"],
            markPx=float(m["markPx"]),
            ts=str(m.get("ts", "")),
        )
