"""Bounded in-memory cache with TTL and LRU eviction.

Used as a fallback when Redis/Supabase is unavailable. Not suitable for
multi-process deployments, but prevents unbounded growth in single-process
local dev / test environments.
"""

import threading
import time
from collections import OrderedDict
from typing import Generic, TypeVar

T = TypeVar("T")


class MemoryCache(Generic[T]):
    """Thread-safe in-memory cache with TTL and LRU eviction.

    Args:
        max_size: Maximum number of entries before LRU eviction.
        ttl_seconds: Time-to-live for each entry.
    """

    def __init__(self, max_size: int = 256, ttl_seconds: int = 3600):
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._data: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> T | None:
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires_at, value = item
            if now > expires_at:
                del self._data[key]
                return None
            # Move to end (most recently used).
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: T) -> None:
        now = time.time()
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (now + self._ttl_seconds, value)
            # Evict oldest items if over capacity.
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def keys(self):
        with self._lock:
            return list(self._data.keys())

    def values(self):
        now = time.time()
        with self._lock:
            return [value for expires_at, value in self._data.values() if now <= expires_at]
