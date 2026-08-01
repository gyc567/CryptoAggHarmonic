"""Unified Redis client factory.

Supports both traditional redis-py (redis:// / rediss://) and Upstash Redis
REST (UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN). Consumers that only
need basic get/set/ping can use either backend transparently.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def get_redis_client() -> Any | None:
    """Return a Redis client compatible with get/set/ping or None.

    Priority:
    1. Upstash Redis REST when UPSTASH_REDIS_REST_URL is set.
    2. redis-py when REDIS_URL starts with redis:// or rediss://.
    3. None (consumer falls back to in-memory).
    """
    upstash_url = os.getenv("UPSTASH_REDIS_REST_URL")
    upstash_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if upstash_url and upstash_token:
        try:
            from upstash_redis import Redis as UpstashRedis

            client = UpstashRedis(url=upstash_url, token=upstash_token)
            client.ping()
            logger.info("Redis client: Upstash REST connected")
            return client
        except Exception as e:
            logger.warning("Upstash Redis REST connection failed: %s", e)

    redis_url = os.getenv("REDIS_URL", "")
    if redis_url.startswith(("redis://", "rediss://")):
        try:
            import redis

            client = redis.from_url(redis_url, decode_responses=True)
            client.ping()
            logger.info("Redis client: redis-py connected")
            return client
        except Exception as e:
            logger.warning("redis-py connection failed: %s", e)

    return None
