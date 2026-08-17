"""Simple in-memory rate limiter using sliding window.

No external dependencies — uses only stdlib. Thread-safe with threading.Lock.
Production deployment should use Redis-backed storage (see note below).

Usage:
    from app.api.rate_limit import RateLimiter, rate_limit

    limiter = RateLimiter()
    app.register_extension("rate_limiter", limiter)

    @api_bp.route("/api/analyze", methods=["POST"])
    @require_auth
    @limiter.limit("10/minute")
    def analyze(user):
        ...

Production note:
    The in-memory store does NOT survive gunicorn worker restarts.
    For production, replace the store with Redis:
        from redis import Redis
        class RedisRateLimiter(RateLimiter):
            def _get_window(self, key, window_seconds):
                # Use Redis sorted set with ZREMRANGEBYSCORE + ZCARD
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from functools import wraps
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Rate limit configuration for an endpoint."""

    requests: int  # max requests
    window_seconds: int  # time window


class SlidingWindowStore:
    """Thread-safe sliding window rate limit store.

    Uses a simple list of timestamps per key. Prunes old entries on each
    check. Good enough for single-worker deployments; swap to Redis for
    multi-worker production use.
    """

    def __init__(self) -> None:
        self._data: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _prune(self, key: str, cutoff: float) -> None:
        """Remove timestamps older than cutoff."""
        self._data[key] = [t for t in self._data[key] if t > cutoff]

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """Return True if request is allowed, False if rate limited."""
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            self._prune(key, cutoff)
            count = len(self._data[key])

            if count >= max_requests:
                return False

            self._data[key].append(now)
            return True

    def remaining(self, key: str, max_requests: int, window_seconds: int) -> int:
        """Return number of remaining requests in current window."""
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            self._prune(key, cutoff)
            return max(0, max_requests - len(self._data[key]))

    def reset(self, key: str) -> None:
        """Reset all entries for a key."""
        with self._lock:
            self._data.pop(key, None)


class RateLimiter:
    """In-memory rate limiter with per-user, per-endpoint limits."""

    DEFAULT_LIMITS: dict[str, RateLimitConfig] = {
        # Core endpoints — tighter limits to prevent abuse
        "analyze": RateLimitConfig(requests=10, window_seconds=60),  # 10/min
        "batch_quotes": RateLimitConfig(requests=30, window_seconds=60),  # 30/min
        # Watchlist operations
        "watchlist_crud": RateLimitConfig(requests=60, window_seconds=60),  # 60/min
        # Read-heavy endpoints — looser
        "history": RateLimitConfig(requests=120, window_seconds=60),  # 120/min
        "health": RateLimitConfig(requests=300, window_seconds=60),  # 300/min
        # Admin endpoints
        "admin": RateLimitConfig(requests=10, window_seconds=60),  # 10/min
    }

    def __init__(self, store: SlidingWindowStore | None = None) -> None:
        self._store = store or SlidingWindowStore()

    def _key_for(self, user_id: str | None, endpoint: str) -> str:
        """Build rate limit key from user and endpoint."""
        uid = user_id or "anonymous"
        return f"{uid}:{endpoint}"

    def check(self, user_id: str | None, endpoint: str) -> tuple[bool, int, int]:
        """Check if request is allowed.

        Returns (allowed, remaining, reset_in_seconds).
        reset_in_seconds is seconds until oldest entry expires (0 if allowed).
        """
        config = self.DEFAULT_LIMITS.get(endpoint, RateLimitConfig(requests=60, window_seconds=60))
        key = self._key_for(user_id, endpoint)

        allowed = self._store.is_allowed(key, config.requests, config.window_seconds)
        remaining = self._store.remaining(key, config.requests, config.window_seconds)

        if allowed:
            return True, remaining, 0

        # Calculate seconds until oldest entry expires
        now = time.monotonic()
        with self._store._lock:
            timestamps = self._store._data.get(key, [])
            if timestamps:
                oldest = min(timestamps)
                reset_in = int(oldest + config.window_seconds - now) + 1
            else:
                reset_in = config.window_seconds

        return False, 0, max(1, reset_in)

    def limit(self, endpoint: str) -> Callable:
        """Decorator to apply rate limiting to a route.

        Usage:
            @limiter.limit("analyze")
            @require_auth
            def analyze(user):
                ...
        """
        def decorator(fn: Callable) -> Callable:
            @wraps(fn)
            def wrapper(*args, **kwargs):
                # Extract user from kwargs (set by require_auth decorator)
                user = kwargs.get("user")
                user_id = str(user.get("id")) if user else None

                allowed, remaining, reset_in = self.check(user_id, endpoint)

                if not allowed:
                    from flask import jsonify, make_response
                    logger.warning("Rate limit exceeded: user=%s endpoint=%s", user_id, endpoint)
                    response = make_response(
                        jsonify({
                            "success": False,
                            "error": {
                                "code": "RATE_LIMITED",
                                "message": f"Rate limit exceeded. Try again in {reset_in} seconds.",
                                "retry_after_seconds": reset_in,
                            }
                        }),
                        429,
                    )
                    response.headers["Retry-After"] = str(reset_in)
                    response.headers["X-RateLimit-Remaining"] = "0"
                    return response

                # Add rate limit headers to successful responses
                response = fn(*args, **kwargs)
                if hasattr(response, "headers"):
                    response.headers["X-RateLimit-Remaining"] = str(remaining)
                return response

            return wrapper
        return decorator


# Global limiter instance — initialized once at app startup
_limiter: RateLimiter | None = None


def get_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
