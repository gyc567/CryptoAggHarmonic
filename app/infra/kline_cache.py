"""K-line data cache with Redis-backed storage and in-memory fallback.

K线数据对同一 symbol/interval/limit 是稳定的，使用指纹缓存
（最后一根K线时间戳+数量+收盘价）实现自然失效。

环境变量:
- KLINE_CACHE_ENABLED: "false" 关闭缓存（默认开启）
- KLINE_CACHE_TTL_SECONDS: 兜底 TTL（默认 900 = 15分钟）
- REDIS_URL: 未配置时使用进程内内存缓存
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import pandas as pd

from app.infra.memory_cache import MemoryCache
from app.infra.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Default TTL: 15 minutes (allows K-line to change during formation)
_DEFAULT_TTL_SECONDS = 900
_KEY_PREFIX = "kline:v1:"

# Data version for cache invalidation
DATA_VERSION = "v1"


@dataclass
class KLineMeta:
    """Metadata for cached K-line data."""
    source: str              # "tradingview" | "ccxt" | "binance"
    exchange: str            # "binance" | "okx" | "bybit"
    symbol: str
    interval: str
    fetched_at: str          # ISO timestamp
    latency_ms: float
    version: str = DATA_VERSION


class KLineCache:
    """Cache K-line DataFrame keyed by request params + candle fingerprint."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ):
        self.enabled = os.getenv("KLINE_CACHE_ENABLED", "true").lower() not in ("0", "false", "no")
        self.ttl_seconds = ttl_seconds or int(os.getenv("KLINE_CACHE_TTL_SECONDS", str(_DEFAULT_TTL_SECONDS)))
        self._redis_url = redis_url if redis_url is not None else os.getenv("REDIS_URL", "")
        self._redis: Optional[Any] = None
        # Bounded in-memory fallback: 256 entries, same TTL as Redis.
        self._memory = MemoryCache[dict](max_size=256, ttl_seconds=self.ttl_seconds)
        # Index for pattern-based invalidation: maps pattern-hash to list of keys
        self._pattern_index: dict[str, set[str]] = {}
        if self.enabled:
            self._connect()

    def _connect(self) -> None:
        try:
            self._redis = get_redis_client()
            if self._redis is None:
                logger.info("KLineCache: Redis not configured, using in-memory cache")
        except Exception as e:
            logger.warning("KLineCache: Redis unavailable (%s), using in-memory cache", e)
            self._redis = None

    @staticmethod
    def candle_fingerprint(df: "pd.DataFrame") -> str:
        """Fingerprint based on last candle timestamp + count + last close.

        New candle closes -> timestamp changes -> cache naturally expires.
        """
        if df is None or len(df) == 0:
            return hashlib.sha1(b"empty", usedforsecurity=False).hexdigest()[:16]
        try:
            # Try standard columns
            raw = "{}|{}|{}".format(
                str(df["dts"].iloc[-1]),
                len(df),
                str(df["close"].iloc[-1]),
            )
        except (KeyError, IndexError):
            # Fallback: use index-based columns
            try:
                raw = "{}|{}|{}".format(
                    str(df.index[-1]),
                    len(df),
                    str(df.iloc[-1].get("close", "")),
                )
            except (IndexError, AttributeError):
                # Last resort: hash entire dataframe shape
                raw = f"{len(df)}|{list(df.columns)}"
        return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:16]

    def make_key(
        self,
        *,
        market: str,
        symbol: str,
        interval: str,
        limit: int,
    ) -> str:
        """Generate cache key from request parameters."""
        raw = "|".join(str(v) for v in (market, symbol, interval, limit))
        return _KEY_PREFIX + hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()

    def get(
        self,
        key: str,
    ) -> tuple[Optional["pd.DataFrame"], Optional[KLineMeta]]:
        """Get cached K-line data.

        Returns:
            Tuple of (DataFrame, meta) or (None, None) if cache miss.
        """
        if not self.enabled:
            return None, None
        try:
            payload = self._get_raw(key)
        except Exception as e:
            logger.warning("KLineCache get failed: %s", e)
            return None, None
        if payload is None:
            return None, None

        try:
            entry = json.loads(payload)
            df_dict = entry.get("df")
            if df_dict is None:
                return None, None

            import pandas as pd
            df = pd.DataFrame(df_dict["data"], columns=df_dict["columns"])
            if "dts" in df_dict:
                df["dts"] = pd.to_datetime(df_dict["dts"])
            if "index" in df_dict and isinstance(df_dict["index"], list):
                df.index = pd.to_datetime(df_dict["index"])

            meta_dict = entry.get("meta", {})
            meta = KLineMeta(**meta_dict) if meta_dict else None

            logger.debug("KLineCache HIT: %s", key)
            return df, meta
        except Exception as e:
            logger.warning("KLineCache decode failed: %s", e)
            return None, None

    def set(
        self,
        key: str,
        df: "pd.DataFrame",
        meta: KLineMeta,
    ) -> None:
        """Cache K-line DataFrame with metadata."""
        if not self.enabled:
            return
        try:
            # Serialize DataFrame
            df_dict = {
                "data": df.values.tolist(),
                "columns": df.columns.tolist(),
            }
            # Convert datetime columns to ISO strings
            dts_col = "dts" if "dts" in df.columns else None
            if dts_col:
                # Use apply with isoformat to handle datetime correctly
                df_dict["dts"] = df[dts_col].apply(lambda x: x.isoformat() if hasattr(x, 'isoformat') else str(x)).tolist()
            if df.index.name and df.index.name != "dts":
                df_dict["index"] = df.index.astype(str).tolist()

            entry = {
                "df": df_dict,
                "meta": asdict(meta),
            }
            self._set_raw(key, json.dumps(entry, default=str))

            # Store params for pattern-based invalidation (only for memory cache)
            if self._redis is None and hasattr(self, '_pattern_index'):
                params_key = f"{meta.exchange}:{meta.symbol}:{meta.interval}"
                if params_key not in self._pattern_index:
                    self._pattern_index[params_key] = set()
                self._pattern_index[params_key].add(key)

            logger.debug("KLineCache SET: %s", key)
        except Exception as e:
            logger.warning("KLineCache set failed: %s", e)

    def _get_raw(self, key: str) -> Optional[str]:
        if self._redis is not None:
            return self._redis.get(key)
        return self._memory.get(key)

    def _set_raw(self, key: str, payload: str) -> None:
        if self._redis is not None:
            self._redis.setex(key, self.ttl_seconds, payload)
        else:
            self._memory.set(key, payload)

    def invalidate(self, pattern: str = "*") -> int:
        """Invalidate cache entries matching pattern.

        Args:
            pattern: Glob pattern, e.g. "binance:BTCUSDT:*" or just "*BTC*"

        Returns:
            Number of keys deleted.
        """
        if not self.enabled:
            return 0
        if self._redis is not None:
            try:
                keys = self._redis.keys(_KEY_PREFIX + pattern)
                if keys:
                    return self._redis.delete(*keys)
            except Exception as e:
                logger.warning("KLineCache invalidate failed: %s", e)
        # Memory cache invalidation
        if self._memory and hasattr(self, '_pattern_index'):
            try:
                # Use the pattern index for efficient lookup
                import re
                regex_pattern = pattern.replace("*", ".*").replace("?", ".")
                regex = re.compile(regex_pattern)

                # Find all params keys that match the pattern
                keys_to_delete = set()
                for params_key in list(self._pattern_index.keys()):
                    if regex.search(params_key):
                        keys_to_delete.update(self._pattern_index[params_key])

                # Delete the matching keys
                for key in keys_to_delete:
                    self._memory.delete(key)

                # Clean up the pattern index
                for params_key in list(self._pattern_index.keys()):
                    self._pattern_index[params_key] -= keys_to_delete
                    if not self._pattern_index[params_key]:
                        del self._pattern_index[params_key]

                return len(keys_to_delete)
            except Exception as e:
                logger.warning("KLineCache invalidate (memory) failed: %s", e)
        return 0


# Process-wide singleton
_default_cache: Optional[KLineCache] = None
_default_lock = threading.Lock()


def get_kline_cache() -> KLineCache:
    """Get the process-wide shared cache instance (lazy)."""
    global _default_cache
    if _default_cache is None:
        with _default_lock:
            if _default_cache is None:
                _default_cache = KLineCache()
    return _default_cache


def reset_kline_cache() -> None:
    """Reset the shared instance (tests only)."""
    global _default_cache
    with _default_lock:
        _default_cache = None
