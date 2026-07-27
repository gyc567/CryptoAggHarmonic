"""Analysis result cache (Redis-backed, in-memory fallback).

形态检测结果对同一组 K 线是完全确定的，因此以 (请求参数 + K线指纹) 为键缓存
整个 AnalysisData JSON 与图表 PNG。命中时跳过形态检测、LLM 解读和 Kaleido
渲染，响应从秒级降到毫秒级。

缓存键中的 K线指纹 = 最后一根 K 线时间戳 + K线数 + 最新收盘价；新 K 线收盘后
指纹变化，缓存自然失效，TTL 仅作为兜底。

环境变量:
- ANALYSIS_CACHE_ENABLED: "false" 关闭缓存（默认开启）
- ANALYSIS_CACHE_TTL_SECONDS: 兜底 TTL（默认 21600 = 6 小时）
- REDIS_URL: 未配置或连接失败时退化为进程内内存缓存
"""
import base64
import hashlib
import json
import logging
import os
import threading
from typing import Any, Optional

import pandas as pd

from app.infra.memory_cache import MemoryCache

logger = logging.getLogger(__name__)

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore

_DEFAULT_TTL_SECONDS = 6 * 3600
_KEY_PREFIX = "analysis:v1:"


class AnalysisCache:
    """Cache AnalysisData JSON + chart PNG keyed by request + candle fingerprint."""

    def __init__(self, redis_url: Optional[str] = None, ttl_seconds: Optional[int] = None):
        self.enabled = os.getenv("ANALYSIS_CACHE_ENABLED", "true").lower() not in ("0", "false", "no")
        self.ttl_seconds = ttl_seconds or int(
            os.getenv("ANALYSIS_CACHE_TTL_SECONDS", str(_DEFAULT_TTL_SECONDS))
        )
        self.redis_url = redis_url if redis_url is not None else os.getenv("REDIS_URL", "")
        self._redis: Optional[Any] = None
        # Bounded in-memory fallback: 256 entries, same TTL as Redis.
        self._memory = MemoryCache[str](max_size=256, ttl_seconds=self.ttl_seconds)
        if self.enabled:
            self._connect()

    def _connect(self) -> None:
        if not self.redis_url or redis is None:
            logger.info("Analysis cache: Redis not configured, using in-memory cache")
            return
        try:
            self._redis = redis.from_url(self.redis_url, decode_responses=True)
            self._redis.ping()
            logger.info("Analysis cache: Redis connected")
        except Exception as e:
            logger.warning("Analysis cache: Redis unavailable (%s), using in-memory cache", e)
            self._redis = None

    @staticmethod
    def candle_fingerprint(candle_data: Any) -> str:
        """Fingerprint of the underlying candles: last timestamp + count + last close.

        新 K 线收盘后最后一根时间戳变化，缓存自然失效。
        """
        df = candle_data.df
        if not isinstance(df, pd.DataFrame):
            # 非真实 DataFrame（如测试 Mock）：用 repr（含对象 id）散列，
            # 避免不同对象被误判为同一份数据导致跨调用缓存碰撞
            return hashlib.sha1(repr(df).encode()).hexdigest()[:16]
        if len(df) == 0:
            # 空数据无法取指纹：退化为固定值，宁可 miss，不可错 hit 或抛异常
            return hashlib.sha1(b"empty").hexdigest()[:16]
        try:
            raw = "{}|{}|{}".format(str(df["dts"].iloc[-1]), len(df), str(df["close"].iloc[-1]))
        except Exception:
            # 列名不符预期时退化为末行哈希：宁可 miss，不可错 hit
            raw = str(df.iloc[-1].to_dict())
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def make_key(
        self,
        *,
        market: str,
        symbol: str,
        interval: str,
        analysis_type: str,
        limit_to: int,
        percent_complete: float,
        candles: int,
        fingerprint: str,
    ) -> str:
        raw = "|".join(
            str(v)
            for v in (
                market,
                symbol,
                interval,
                analysis_type,
                limit_to,
                round(float(percent_complete), 4),
                candles,
                fingerprint,
            )
        )
        return _KEY_PREFIX + hashlib.sha1(raw.encode()).hexdigest()

    def get(self, key: str) -> Optional[dict]:
        """Return {"analysis_json": str, "chart_png": bytes|None} or None."""
        if not self.enabled:
            return None
        try:
            payload = self._get_raw(key)
        except Exception as e:
            logger.warning("Analysis cache get failed: %s", e)
            return None
        if payload is None:
            return None
        try:
            entry = json.loads(payload)
            chart_png = None
            if entry.get("chart_png_b64"):
                chart_png = base64.b64decode(entry["chart_png_b64"])
            logger.info("Analysis cache HIT: %s", key)
            return {"analysis_json": entry["analysis_json"], "chart_png": chart_png}
        except Exception as e:
            logger.warning("Analysis cache decode failed: %s", e)
            return None

    def set(self, key: str, analysis_json: str, chart_png: Optional[bytes] = None) -> None:
        if not self.enabled:
            return
        entry = {
            "analysis_json": analysis_json,
            "chart_png_b64": base64.b64encode(chart_png).decode() if chart_png else None,
        }
        try:
            self._set_raw(key, json.dumps(entry))
        except Exception as e:
            logger.warning("Analysis cache set failed: %s", e)

    def _get_raw(self, key: str) -> Optional[str]:
        if self._redis is not None:
            return self._redis.get(key)
        return self._memory.get(key)

    def _set_raw(self, key: str, payload: str) -> None:
        if self._redis is not None:
            self._redis.setex(key, self.ttl_seconds, payload)
            return
        self._memory.set(key, payload)


_default_cache: Optional[AnalysisCache] = None
_default_lock = threading.Lock()


def get_analysis_cache() -> AnalysisCache:
    """Process-wide shared cache instance (lazy)."""
    global _default_cache
    if _default_cache is None:
        with _default_lock:
            if _default_cache is None:
                _default_cache = AnalysisCache()
    return _default_cache


def reset_analysis_cache() -> None:
    """Reset the shared instance (tests)."""
    global _default_cache
    with _default_lock:
        _default_cache = None
