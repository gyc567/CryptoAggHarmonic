"""RQ worker entry point for vibe agent tasks."""

import logging
import os
import sys

# Ensure project root is on path for imports.
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from redis import Redis  # noqa: E402  — sys.path must be patched before imports
from rq import Connection, Queue, Worker  # noqa: E402  — sys.path must be patched before imports

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO)
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_conn = Redis.from_url(redis_url)

    with Connection(redis_conn):
        queues = [Queue("vibe")]
        worker = Worker(queues)
        logger.info("Vibe worker started, listening on 'vibe' queue")
        worker.work()


if __name__ == "__main__":
    main()
