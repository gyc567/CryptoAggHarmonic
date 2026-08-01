"""Event store for vibe run events.

Uses Redis lists as the primary backend. Falls back to an in-memory store
when Redis is unavailable (local dev / tests).
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import TypeAdapter, ValidationError

from app.domain.vibe_schemas import VibeEvent
from app.infra.memory_cache import MemoryCache

logger = logging.getLogger(__name__)


try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore


_VIBE_EVENT_ADAPTER = TypeAdapter(VibeEvent)


class VibeEventStore:
    """Store and retrieve run events for SSE / polling.

    Each event carries an in-run, 0-indexed ``seq`` that callers can use to
    resume polling after a disconnect. ``after_seq`` triggers an indexed
    Redis LRANGE (O(log N)) instead of the older event_id scan (O(N)).
    """

    def __init__(self, redis_url: Optional[str] = None, ttl_seconds: int = 3600):
        # ``redis_url=""`` is the explicit test-only switch for memory mode.
        # ``None`` means auto-detect any configured shared backend, including
        # Upstash REST when REDIS_URL itself is intentionally absent.
        self._force_memory = redis_url == ""
        self._auto_detect = redis_url is None
        self.redis_url = os.getenv("REDIS_URL", "") if redis_url is None else redis_url
        self.ttl_seconds = ttl_seconds
        self._redis: Optional[Any] = None
        # Bounded in-memory fallback for events.
        self._memory = MemoryCache[list[dict]](max_size=256, ttl_seconds=ttl_seconds)
        # In-memory per-run seq counters used when Redis is unavailable.
        self._seq_memory: dict[str, int] = {}
        self._connect()

    def _connect(self) -> None:
        # Tests can force in-memory by passing redis_url="".
        if self._force_memory:
            return

        # Prefer the shared Redis client factory (supports Upstash REST, redis-py, etc.).
        if self._auto_detect:
            try:
                from app.infra.redis_client import get_redis_client

                client = get_redis_client()
                if client is not None:
                    self._redis = client
                    logger.info("VibeEventStore connected via shared Redis client")
                    return
            except Exception as e:
                logger.warning("Shared Redis client failed for VibeEventStore: %s", e)

        # Fallback to a direct redis-py connection when REDIS_URL is explicit.
        if self.redis_url and redis is not None:
            try:
                self._redis = redis.from_url(self.redis_url, decode_responses=True)
                self._redis.ping()
                logger.info("VibeEventStore connected to Redis")
                return
            except Exception as e:
                logger.warning("Failed to connect to Redis: %s; using in-memory store", e)

        logger.warning("Redis not configured; using in-memory event store")

    def _pipeline(self):
        """Return a pipeline/context manager if the Redis client supports it."""
        if self._redis is None:
            return None
        if hasattr(self._redis, "pipeline"):
            return self._redis.pipeline()
        return None

    def _key(self, run_id: str) -> str:
        return f"vibe:run:{run_id}:events"

    def _seq_key(self, run_id: str) -> str:
        return f"vibe:run:{run_id}:next_seq"

    def _next_seq(self, run_id: str) -> int:
        """Allocate the next per-run sequence number.

        Redis path: ``INCR`` is atomic and serves all worker processes.
        Memory path: a plain dict incremented under the GIL — sufficient for
        single-process dev / test runs.
        """
        if self._redis:
            try:
                # Redis INCR returns 1 for a missing key; event sequences are
                # deliberately zero-based so seq maps directly to LRANGE index.
                seq = int(self._redis.incr(self._seq_key(run_id))) - 1
                self._redis.expire(self._seq_key(run_id), self.ttl_seconds)
                return seq
            except Exception as e:  # noqa: BLE001 - degrade to memory
                logger.warning("Redis INCR failed, falling back to memory seq: %s", e)
        nxt = self._seq_memory.get(run_id, -1) + 1
        self._seq_memory[run_id] = nxt
        return nxt

    def publish(self, run_id: str, event: dict) -> str:
        """Publish an event after schema validation. Returns the assigned event_id."""
        # Backfill required fields before validating so callers can stay terse.
        if not event.get("event_id"):
            event["event_id"] = self._generate_event_id()
        event["run_id"] = run_id
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        # Assign the sequence number BEFORE pydantic validation so the
        # discriminated union keeps ``seq`` optional but always populated.
        event.setdefault("seq", self._next_seq(run_id))

        try:
            validated = _VIBE_EVENT_ADAPTER.validate_python(event)
        except ValidationError as e:
            # Don't fail the run for a malformed event; log loud and skip.
            logger.error(
                "Dropping malformed vibe event for run %s: %s | payload=%s",
                run_id,
                e.errors(),
                event,
            )
            return event["event_id"]

        payload = json.dumps(validated.model_dump(), ensure_ascii=False, default=str)

        if self._redis:
            try:
                key = self._key(run_id)
                pipe = self._pipeline()
                if pipe is not None:
                    with pipe:
                        pipe.rpush(key, payload)
                        pipe.expire(key, self.ttl_seconds)
                        # upstash-redis queues commands through ``execute`` and
                        # commits them with ``exec``; redis-py commits with
                        # ``execute`` directly.
                        if hasattr(pipe, "exec"):
                            pipe.exec()
                        else:
                            pipe.execute()
                else:
                    self._redis.rpush(key, payload)
                    self._redis.expire(key, self.ttl_seconds)
                return event["event_id"]
            except Exception as e:
                logger.warning("Redis publish failed, falling back to memory: %s", e)

        events = self._memory.get(run_id) or []
        events.append(validated.model_dump())
        self._memory.set(run_id, events)
        return event["event_id"]

    def get_events(
        self,
        run_id: str,
        after_event_id: Optional[str] = None,
        after_seq: Optional[int] = None,
        offset: Optional[int] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get events for a run.

        Args:
            after_event_id: Return events strictly after this event_id. Backward
                compatible cursor; slower (O(n)) because event_ids are not indexed.
            after_seq: Return events with ``seq > after_seq``. O(log N) on Redis
                via LRANGE; preferred new cursor.
            offset: Return events starting at this list index. Used by the SSE
                path to avoid re-fetching already-streamed events.
            limit: Maximum number of events to return.

        Priority: ``after_seq`` > ``after_event_id`` > ``offset``.
        """
        if after_seq is not None:
            # Indexed LRANGE: with seq 0-indexed, "seq > after_seq" is
            # LRANGE idx = after_seq + 1, length = limit.
            return self._fetch_range(run_id, offset=after_seq + 1, limit=limit)

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
                self._redis.delete(self._seq_key(run_id))
            except Exception as e:
                logger.warning("Redis clear failed: %s", e)
        self._memory.delete(run_id)
        self._seq_memory.pop(run_id, None)

    @staticmethod
    def _generate_event_id() -> str:
        return f"evt_{uuid.uuid4().hex[:16]}"
