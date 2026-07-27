"""Event store for vibe run events.

Uses Redis lists as the primary backend. Falls back to an in-memory store
when Redis is unavailable (local dev / tests).
"""
import json
import logging
import os
import uuid
from typing import Optional, Any
from datetime import datetime, timezone

from app.infra.memory_cache import MemoryCache

logger = logging.getLogger(__name__)


try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore


class VibeEventStore:
    """Store and retrieve run events for SSE / polling."""

    def __init__(self, redis_url: Optional[str] = None, ttl_seconds: int = 3600):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "")
        self.ttl_seconds = ttl_seconds
        self._redis: Optional[Any] = None
        # Bounded in-memory fallback for events.
        self._memory = MemoryCache[list[dict]](max_size=256, ttl_seconds=ttl_seconds)
        self._connect()

    def _connect(self) -> None:
        if not self.redis_url or redis is None:
            logger.warning("Redis not configured; using in-memory event store")
            return
        try:
            self._redis = redis.from_url(self.redis_url, decode_responses=True)
            self._redis.ping()
            logger.info("VibeEventStore connected to Redis")
        except Exception as e:
            logger.warning("Failed to connect to Redis: %s; using in-memory store", e)
            self._redis = None

    def _key(self, run_id: str) -> str:
        return f"vibe:run:{run_id}:events"

    def publish(self, run_id: str, event: dict) -> str:
        """Publish an event. Returns the assigned event_id."""
        event_id = event.get("event_id") or self._generate_event_id()
        event["event_id"] = event_id
        event["run_id"] = run_id
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())

        payload = json.dumps(event, ensure_ascii=False, default=str)

        if self._redis:
            try:
                key = self._key(run_id)
                with self._redis.pipeline() as pipe:
                    pipe.rpush(key, payload)
                    pipe.expire(key, self.ttl_seconds)
                    pipe.execute()
                return event_id
            except Exception as e:
                logger.warning("Redis publish failed, falling back to memory: %s", e)

        events = self._memory.get(run_id) or []
        events.append(event)
        self._memory.set(run_id, events)
        return event_id

    def get_events(
        self,
        run_id: str,
        after_event_id: Optional[str] = None,
        offset: Optional[int] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get events for a run.

        Args:
            after_event_id: Return events strictly after this event_id. Used by
                the polling path; slower (O(n)) because event_ids are not indexed.
            offset: Return events starting at this list index. Used by the SSE
                path to avoid re-fetching already-streamed events.
            limit: Maximum number of events to return.
        """
        if after_event_id is not None:
            # Polling path: filter by event_id for backward compatibility.
            events = self._fetch_all(run_id)
            found = False
            filtered = []
            for ev in events:
                if found:
                    filtered.append(ev)
                elif ev.get("event_id") == after_event_id:
                    found = True
            return filtered[-limit:]

        events = self._fetch_range(run_id, offset=offset or 0, limit=limit)
        return events

    def _fetch_all(self, run_id: str) -> list[dict]:
        if self._redis:
            try:
                key = self._key(run_id)
                raw_list = self._redis.lrange(key, 0, -1)
                events = []
                for raw in raw_list:
                    try:
                        events.append(json.loads(raw))
                    except json.JSONDecodeError:
                        continue
                return events
            except Exception as e:
                logger.warning("Redis fetch failed, falling back to memory: %s", e)
        return list(self._memory.get(run_id) or [])

    def _fetch_range(self, run_id: str, offset: int, limit: int) -> list[dict]:
        """Fetch a slice of events by index; used by SSE to avoid O(n^2)."""
        if self._redis:
            try:
                key = self._key(run_id)
                raw_list = self._redis.lrange(key, offset, offset + limit - 1)
                events = []
                for raw in raw_list:
                    try:
                        events.append(json.loads(raw))
                    except json.JSONDecodeError:
                        continue
                return events
            except Exception as e:
                logger.warning("Redis range fetch failed, falling back to memory: %s", e)
        events = self._memory.get(run_id) or []
        return list(events[offset : offset + limit])

    def clear(self, run_id: str) -> None:
        """Clear events for a run."""
        if self._redis:
            try:
                self._redis.delete(self._key(run_id))
            except Exception as e:
                logger.warning("Redis clear failed: %s", e)
        self._memory.delete(run_id)

    @staticmethod
    def _generate_event_id() -> str:
        return f"evt_{uuid.uuid4().hex[:16]}"
