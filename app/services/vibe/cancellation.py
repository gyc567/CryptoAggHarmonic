"""Cross-process cancellation signalling for vibe runs.

Sync-thread fallbacks run in the same process as the API, so a local
``threading.Event`` is sufficient. RQ workers run in separate processes, so we
also publish a Redis key that workers poll.
"""

import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None


_CANCEL_KEY_TTL_SECONDS = 3600
_RUN_EVENTS: dict[str, threading.Event] = {}
_redis_client: Optional[object] = None


def _get_redis() -> object | None:
    """Return a shared Redis client for cancellation checks, if configured."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if redis is None:
        return None
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        return None
    try:
        _redis_client = redis.from_url(redis_url, decode_responses=True)
        _redis_client.ping()
        logger.info("Cancellation module connected to Redis")
    except Exception as e:
        logger.warning("Cancellation module failed to connect to Redis: %s", e)
        _redis_client = None
    return _redis_client


def _cancel_key(run_id: str) -> str:
    return f"vibe:run:{run_id}:cancelled"


class CancellationToken:
    """Token that can be polled for cancellation across processes."""

    def __init__(
        self,
        run_id: str,
        local_event: threading.Event | None = None,
        redis_client: Optional[object] = None,
    ):
        self.run_id = run_id
        self._local_event = local_event
        self._redis = redis_client

    def set(self) -> None:
        """Signal cancellation."""
        if self._local_event is not None:
            self._local_event.set()
        if self._redis is not None:
            try:
                self._redis.setex(_cancel_key(self.run_id), _CANCEL_KEY_TTL_SECONDS, "1")
            except Exception as e:
                logger.warning("Failed to set Redis cancel key for %s: %s", self.run_id, e)

    def is_set(self) -> bool:
        """Return True if cancellation has been requested."""
        if self._local_event is not None and self._local_event.is_set():
            return True
        if self._redis is not None:
            try:
                return bool(self._redis.exists(_cancel_key(self.run_id)))
            except Exception as e:
                logger.warning("Failed to read Redis cancel key for %s: %s", self.run_id, e)
        return False


def register_run(run_id: str) -> CancellationToken:
    """Create and register a cancellation token for a run."""
    event = threading.Event()
    _RUN_EVENTS[run_id] = event
    return CancellationToken(run_id, local_event=event, redis_client=_get_redis())


def get_token(run_id: str) -> CancellationToken | None:
    """Return an existing cancellation token for a run, if any."""
    event = _RUN_EVENTS.get(run_id)
    return CancellationToken(run_id, local_event=event, redis_client=_get_redis())


def cancel_run(run_id: str) -> bool:
    """Signal cancellation for a run across local event and Redis."""
    token = get_token(run_id)
    if token is not None:
        token.set()
        return True

    # No local token yet (e.g. RQ worker has not started); fall back to Redis.
    redis_client = _get_redis()
    if redis_client is not None:
        try:
            redis_client.setex(_cancel_key(run_id), _CANCEL_KEY_TTL_SECONDS, "1")
            return True
        except Exception as e:
            logger.warning("Failed to set Redis cancel key for %s: %s", run_id, e)
    return False


def unregister_run(run_id: str) -> None:
    """Remove the local cancellation event for a completed run."""
    _RUN_EVENTS.pop(run_id, None)
    redis_client = _get_redis()
    if redis_client is not None:
        try:
            redis_client.delete(_cancel_key(run_id))
        except Exception as e:
            logger.warning("Failed to delete Redis cancel key for %s: %s", run_id, e)
