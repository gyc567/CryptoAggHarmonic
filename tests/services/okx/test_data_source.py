"""Tests OKXMarketData: shape validation for ticker / candles / funding / OI / mark."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.okx.data_source import OKXMarketData
from app.services.okx.mcp_client import OKXToolResult


def _ok(data: Any) -> OKXToolResult:
    return OKXToolResult(ok=True, data=data, code="0", trace_id="t", latency_ms=10)


def _client_with(payloads: dict[str, Any]) -> OKXMarketData:
    client = MagicMock()
    # map tool name → response payload
    client.invoke_tool.side_effect = lambda name, args, is_write: _ok(payloads[name])
    return OKXMarketData(client)


class TestGetTicker:
    def test_valid_ticker(self) -> None:
        ds = _client_with({
            "market_get_ticker": {"data": [{"instId": "BTC-USDT", "last": "65000",
                                            "bidPx": "64999.9", "askPx": "65000.1",
                                            "vol24h": "1234.5", "ts": "1700000000000"}]}
        })
        t = ds.get_ticker("BTC-USDT")
        assert t.instId == "BTC-USDT"
        assert t.last == 65000.0
        assert t.bid == 64999.9
        assert t.ask == 65000.1
        assert t.vol24h == 1234.5

    def test_empty_data_raises(self) -> None:
        ds = _client_with({"market_get_ticker": {"data": []}})
        with pytest.raises(ValueError, match="empty data"):
            ds.get_ticker("BTC-USDT")


class TestGetCandles:
    def test_candle_parsing(self) -> None:
        # OKX candle row: [ts, o, h, l, c, vol, ...]
        ds = _client_with({
            "market_get_candles": {"data": [
                ["1700000000000", "64000", "65000", "63900", "64800", "100.5"],
                ["1700003600000", "64800", "65100", "64700", "65000", "120.0"],
            ]}
        })
        candles = ds.get_candles("BTC-USDT", bar="1h", limit=2)
        assert len(candles) == 2
        assert candles[0].c == 64800.0
        assert candles[1].vol == 120.0


class TestGetFundingRate:
    def test_funding_rate(self) -> None:
        ds = _client_with({
            "market_get_funding_rate": {"data": [{
                "instId": "BTC-USDT-SWAP", "fundingRate": "0.0001",
                "nextFundingTime": "1700000000000", "ts": "1699999900000",
            }]}
        })
        f = ds.get_funding_rate("BTC-USDT-SWAP")
        assert f.fundingRate == 0.0001
        assert f.nextFundingTime == "1700000000000"


class TestGetOpenInterest:
    def test_open_interest_list(self) -> None:
        ds = _client_with({
            "market_get_open_interest": {"data": [
                {"instId": "BTC-USDT-SWAP", "oi": "1234.5", "oiCcy": "BTC", "ts": "1700000000000"},
                {"instId": "ETH-USDT-SWAP", "oi": "56789.0", "oiCcy": "ETH", "ts": "1700000000000"},
            ]}
        })
        oi = ds.get_open_interest("SWAP")
        assert len(oi) == 2
        assert oi[0].oi == 1234.5
        assert oi[1].oiCcy == "ETH"


class TestGetMarkPrice:
    def test_mark_price(self) -> None:
        ds = _client_with({
            "market_get_mark_price": {"data": [{
                "instId": "BTC-USDT-SWAP", "markPx": "65001.5", "ts": "1700000000000"
            }]}
        })
        m = ds.get_mark_price("BTC-USDT-SWAP")
        assert m.markPx == 65001.5
