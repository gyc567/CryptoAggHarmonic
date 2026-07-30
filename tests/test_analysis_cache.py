"""Tests for app.infra.analysis_cache and orchestrator cache integration."""

import base64
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.domain.enums import Interval, Market, Status
from app.domain.schemas import AnalyzeRequest
from app.infra.analysis_cache import AnalysisCache
from app.services.analysis import AnalysisOrchestrator


def _make_candle_data(closes=(100.0, 101.0, 102.0), n=None):
    close_series = list(closes)
    if n is not None:
        # Build a 600-bar synthetic series (rising, with a hammer tail) so the
        # v2 forming view has realistic data to evaluate against.
        close_series = [100.0 + i * 0.2 for i in range(n)]
    df = pd.DataFrame(
        {
            "dts": pd.date_range("2026-01-01", periods=len(close_series), freq="D"),
            "open": close_series,
            "high": close_series,
            "low": close_series,
            "close": close_series,
            "volume": [1.0] * len(close_series),
        }
    )
    # close_time is required by the v2 staleness filter. Use a stable epoch
    # series aligned with the dts column (1d granularity).
    df["close_time"] = (df["dts"].astype("int64") // 10**9).astype("int64")
    return SimpleNamespace(df=df, symbol="BTCUSDT", interval="1d")


def _make_request() -> AnalyzeRequest:
    return AnalyzeRequest(market=Market.BINANCE, symbol="BTCUSDT", interval=Interval.D1)


@pytest.fixture
def cache():
    return AnalysisCache(redis_url="")


class TestFingerprint:
    def test_stable_for_same_data(self):
        cd = _make_candle_data()
        assert AnalysisCache.candle_fingerprint(cd) == AnalysisCache.candle_fingerprint(cd)

    def test_changes_when_last_close_changes(self):
        fp1 = AnalysisCache.candle_fingerprint(_make_candle_data((100.0, 101.0, 102.0)))
        fp2 = AnalysisCache.candle_fingerprint(_make_candle_data((100.0, 101.0, 103.0)))
        assert fp1 != fp2

    def test_changes_when_new_candle_appears(self):
        fp1 = AnalysisCache.candle_fingerprint(_make_candle_data((100.0, 101.0)))
        fp2 = AnalysisCache.candle_fingerprint(_make_candle_data((100.0, 101.0, 102.0)))
        assert fp1 != fp2

    def test_empty_dataframe_does_not_raise(self):
        cd = SimpleNamespace(df=pd.DataFrame(columns=["dts", "close"]))
        assert AnalysisCache.candle_fingerprint(cd)

    def test_missing_columns_fallback(self):
        cd = SimpleNamespace(df=pd.DataFrame({"foo": [1, 2]}))
        assert AnalysisCache.candle_fingerprint(cd)

    def test_non_dataframe_objects_get_distinct_fingerprints(self):
        # MagicMock 等 Mock 对象的 len() 默认为 0，不能被误判为空数据而碰撞
        fp1 = AnalysisCache.candle_fingerprint(SimpleNamespace(df=MagicMock()))
        fp2 = AnalysisCache.candle_fingerprint(SimpleNamespace(df=MagicMock()))
        assert fp1 != fp2


class TestMakeKey:
    def test_same_inputs_same_key(self, cache):
        kwargs = dict(
            market="binance",
            symbol="BTCUSDT",
            interval="1d",
            analysis_type="forming",
            limit_to=10,
            percent_complete=0.8,
            candles=1000,
            fingerprint="abc",
        )
        assert cache.make_key(**kwargs) == cache.make_key(**kwargs)

    def test_differs_on_params_and_fingerprint(self, cache):
        base = dict(
            market="binance",
            symbol="BTCUSDT",
            interval="1d",
            analysis_type="forming",
            limit_to=10,
            percent_complete=0.8,
            candles=1000,
            fingerprint="abc",
        )
        key = cache.make_key(**base)
        assert cache.make_key(**{**base, "symbol": "ETHUSDT"}) != key
        assert cache.make_key(**{**base, "fingerprint": "xyz"}) != key
        assert cache.make_key(**{**base, "analysis_type": "formed"}) != key


class TestSetGet:
    
    def test_roundtrip_without_chart(self, cache):
        cache.set("k2", '{"a": 2}')
        entry = cache.get("k2")
        assert entry["analysis_json"] == '{"a": 2}'
        assert "analysis_json" in entry

    def test_miss_returns_none(self, cache):
        assert cache.get("nonexistent") is None

    def test_expired_entry_returns_none(self):
        cache = AnalysisCache(redis_url="", ttl_seconds=1)
        cache.set("k3", '{"a": 3}')
        future = time.time() + 2
        original_time = time.time
        try:
            time.time = lambda: future
            assert cache.get("k3") is None
        finally:
            time.time = original_time

    def test_disabled_cache(self, monkeypatch):
        monkeypatch.setenv("ANALYSIS_CACHE_ENABLED", "false")
        cache = AnalysisCache(redis_url="")
        cache.set("k4", '{"a": 4}')
        assert cache.get("k4") is None

    

class _Pattern:
    """Stand-in for a pyharmonics pattern (extract_candidates reads .y/.x/etc)."""

    def __init__(self, name, y, completion_min, completion_max, bullish=True, x=None):
        self.name = name
        self.y = y
        self.completion_min_price = completion_min
        self.completion_max_price = completion_max
        self.bullish = bullish
        self.x = x if x is not None else [0, 10, 20, 580, 599]


