"""Tests for app.infra.kline_cache."""

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.infra.kline_cache import (
    DATA_VERSION,
    KLineCache,
    KLineMeta,
    get_kline_cache,
    reset_kline_cache,
)


def _make_df(closes=(100.0, 101.0, 102.0)) -> pd.DataFrame:
    """Create a simple OHLC DataFrame."""
    close_series = list(closes)
    return pd.DataFrame(
        {
            "dts": pd.date_range("2026-01-01", periods=len(close_series), freq="D"),
            "open": close_series,
            "high": close_series,
            "low": close_series,
            "close": close_series,
            "volume": [1.0] * len(close_series),
        }
    )


def _make_meta(
    source: str = "binance",
    exchange: str = "binance",
    symbol: str = "BTCUSDT",
) -> KLineMeta:
    return KLineMeta(
        source=source,
        exchange=exchange,
        symbol=symbol,
        interval="4h",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        latency_ms=50.0,
    )


@pytest.fixture
def cache():
    """Create a fresh cache instance using in-memory backend."""
    reset_kline_cache()
    yield KLineCache(redis_url="")
    reset_kline_cache()


class TestKLineMeta:
    """Tests for KLineMeta dataclass."""

    def test_create_meta(self):
        meta = KLineMeta(
            source="tradingview",
            exchange="binance",
            symbol="BTCUSDT",
            interval="4h",
            fetched_at="2026-01-01T00:00:00Z",
            latency_ms=100.0,
        )
        assert meta.source == "tradingview"
        assert meta.exchange == "binance"
        assert meta.symbol == "BTCUSDT"
        assert meta.interval == "4h"
        assert meta.latency_ms == 100.0
        assert meta.version == DATA_VERSION

    def test_meta_default_version(self):
        meta = KLineMeta(
            source="ccxt",
            exchange="okx",
            symbol="ETHUSDT",
            interval="1h",
            fetched_at="2026-01-01T00:00:00Z",
            latency_ms=0.0,
        )
        assert meta.version == DATA_VERSION


class TestFingerprint:
    """Tests for candle fingerprint generation."""

    def test_same_data_same_fingerprint(self):
        df = _make_df([100.0, 101.0, 102.0])
        fp1 = KLineCache.candle_fingerprint(df)
        fp2 = KLineCache.candle_fingerprint(df)
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_different_closes_different_fingerprint(self):
        df1 = _make_df([100.0, 101.0, 102.0])
        df2 = _make_df([100.0, 101.0, 103.0])
        assert KLineCache.candle_fingerprint(df1) != KLineCache.candle_fingerprint(df2)

    def test_new_candle_changes_fingerprint(self):
        df1 = _make_df([100.0, 101.0])
        df2 = _make_df([100.0, 101.0, 102.0])
        assert KLineCache.candle_fingerprint(df1) != KLineCache.candle_fingerprint(df2)

    def test_empty_df_returns_hash(self):
        df = pd.DataFrame(columns=["dts", "close"])
        fp = KLineCache.candle_fingerprint(df)
        assert fp is not None
        assert len(fp) == 16

    def test_none_df_returns_hash(self):
        fp = KLineCache.candle_fingerprint(None)
        assert fp is not None
        assert len(fp) == 16

    def test_missing_columns_fallback(self):
        df = pd.DataFrame({"foo": [1, 2, 3]})
        fp = KLineCache.candle_fingerprint(df)
        assert fp is not None


class TestMakeKey:
    """Tests for cache key generation."""

    def test_same_params_same_key(self, cache):
        key1 = cache.make_key(
            market="binance",
            symbol="BTCUSDT",
            interval="4h",
            limit=1000,
        )
        key2 = cache.make_key(
            market="binance",
            symbol="BTCUSDT",
            interval="4h",
            limit=1000,
        )
        assert key1 == key2

    def test_different_symbol_different_key(self, cache):
        key1 = cache.make_key(
            market="binance",
            symbol="BTCUSDT",
            interval="4h",
            limit=1000,
        )
        key2 = cache.make_key(
            market="binance",
            symbol="ETHUSDT",
            interval="4h",
            limit=1000,
        )
        assert key1 != key2

    def test_different_interval_different_key(self, cache):
        key1 = cache.make_key(
            market="binance",
            symbol="BTCUSDT",
            interval="4h",
            limit=1000,
        )
        key2 = cache.make_key(
            market="binance",
            symbol="BTCUSDT",
            interval="1h",
            limit=1000,
        )
        assert key1 != key2

    def test_different_limit_different_key(self, cache):
        key1 = cache.make_key(
            market="binance",
            symbol="BTCUSDT",
            interval="4h",
            limit=1000,
        )
        key2 = cache.make_key(
            market="binance",
            symbol="BTCUSDT",
            interval="4h",
            limit=500,
        )
        assert key1 != key2


class TestSetGet:
    """Tests for cache set/get operations."""

    def test_roundtrip(self, cache):
        df = _make_df([100.0, 101.0, 102.0])
        meta = _make_meta()
        key = cache.make_key(
            market="binance",
            symbol="BTCUSDT",
            interval="4h",
            limit=1000,
        )
        cache.set(key, df, meta)
        cached_df, cached_meta = cache.get(key)
        assert cached_df is not None
        assert cached_meta is not None
        assert len(cached_df) == len(df)
        assert cached_meta.source == meta.source

    def test_miss_returns_none(self, cache):
        cached_df, cached_meta = cache.get("nonexistent_key")
        assert cached_df is None
        assert cached_meta is None

    def test_expired_entry_returns_none(self):
        cache = KLineCache(redis_url="", ttl_seconds=1)
        df = _make_df([100.0, 101.0])
        meta = _make_meta()
        key = cache.make_key(
            market="binance",
            symbol="BTCUSDT",
            interval="4h",
            limit=1000,
        )
        cache.set(key, df, meta)

        # Simulate time passing
        with patch("time.time", return_value=time.time() + 10):
            cached_df, cached_meta = cache.get(key)
            assert cached_df is None

    def test_disabled_cache(self, cache, monkeypatch):
        monkeypatch.setenv("KLINE_CACHE_ENABLED", "false")
        cache_disabled = KLineCache(redis_url="")
        df = _make_df([100.0, 101.0])
        meta = _make_meta()
        key = cache_disabled.make_key(
            market="binance",
            symbol="BTCUSDT",
            interval="4h",
            limit=1000,
        )
        cache_disabled.set(key, df, meta)
        cached_df, cached_meta = cache_disabled.get(key)
        assert cached_df is None

    def test_set_after_get_updates(self, cache):
        df1 = _make_df([100.0, 101.0])
        df2 = _make_df([200.0, 201.0])
        meta = _make_meta()
        key = cache.make_key(
            market="binance",
            symbol="BTCUSDT",
            interval="4h",
            limit=1000,
        )
        cache.set(key, df1, meta)
        cache.set(key, df2, meta)
        cached_df, _ = cache.get(key)
        assert cached_df is not None
        assert cached_df["close"].iloc[-1] == 201.0


class TestInvalidate:
    """Tests for cache invalidation."""

    def test_invalidate_pattern(self, cache):
        df = _make_df([100.0, 101.0])
        meta = _make_meta()
        key = cache.make_key(
            market="binance",
            symbol="BTCUSDT",
            interval="4h",
            limit=1000,
        )
        cache.set(key, df, meta)
        assert cache.get(key)[0] is not None
        cache.invalidate("*")
        assert cache.get(key)[0] is None

    def test_invalidate_specific(self, cache):
        df = _make_df([100.0, 101.0])
        key1 = cache.make_key(
            market="binance",
            symbol="BTCUSDT",
            interval="4h",
            limit=1000,
        )
        key2 = cache.make_key(
            market="binance",
            symbol="ETHUSDT",
            interval="4h",
            limit=1000,
        )
        meta1 = _make_meta(symbol="BTCUSDT")
        meta2 = _make_meta(symbol="ETHUSDT")
        cache.set(key1, df, meta1)
        cache.set(key2, df, meta2)
        cache.invalidate("BTCUSDT*")
        assert cache.get(key1)[0] is None
        assert cache.get(key2)[0] is not None


class TestGetKLineCache:
    """Tests for the singleton getter."""

    def test_returns_singleton(self):
        reset_kline_cache()
        cache1 = get_kline_cache()
        cache2 = get_kline_cache()
        assert cache1 is cache2

    def test_reset_clears_singleton(self):
        reset_kline_cache()
        cache1 = get_kline_cache()
        reset_kline_cache()
        cache2 = get_kline_cache()
        assert cache1 is not cache2


class TestEdgeCases:
    """Edge case tests."""

    def test_df_with_index_column(self):
        df = _make_df([100.0, 101.0])
        df.set_index("dts", inplace=True)
        fp = KLineCache.candle_fingerprint(df)
        assert fp is not None

    def test_multiindex_df(self):
        df = _make_df([100.0, 101.0])
        df = df.set_index(["dts", "close"])
        fp = KLineCache.candle_fingerprint(df)
        assert fp is not None

    def test_large_df(self):
        df = _make_df(range(10000))
        fp = KLineCache.candle_fingerprint(df)
        assert fp is not None
        assert len(fp) == 16

    def test_single_row_df(self):
        df = _make_df([100.0])
        fp = KLineCache.candle_fingerprint(df)
        assert fp is not None
