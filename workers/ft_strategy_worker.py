"""FT Strategy worker — Phase 5 stub.

Consumes 4 RQ queues:
  - ft_strategy_create
  - ft_hyperopt
  - ft_backtest
  - ft_analyze

``--dry-run`` (default) prints the queue/job pair without actually shelling
out to ``freqtrade_dev_mcp``. With ``--live`` (and the Loop #13 source
mutex + Keychain credentials in place) the worker would invoke the
MCP client.

ADR-0012 D3: worker respects ``MCP_TIMEOUT_SECONDS=1800`` and
``MAX_BACKTEST_PER_GEN=5`` from ``app.services.freqtrade.mcp_client`` —
DO NOT override these in the worker. If you need a longer limit, change
the constant (and re-run the test suite).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from typing import Any, Optional

# RQ is a runtime-only dep; in tests / dry-run we don't actually need it.
try:
    from rq import Queue, Worker  # noqa: F401  - type registration only
    RQ_AVAILABLE = True
except ImportError:
    RQ_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerJob:
    """Description of a job to process. Pure dataclass for testability."""

    queue: str
    job_id: str
    strategy_id: str
    payload: dict[str, Any]

    def queue_job_pair(self) -> tuple[str, str]:
        return self.queue, self.job_id


@dataclass
class WorkerResult:
    ok: bool
    queue: str
    job_id: str
    detail: str = ""


class FTStrategyWorker:
    """Process Loop #13 jobs.

    The real worker would:
      1. pick up the next RQ job from a queue
      2. call the corresponding ``app.services.freqtrade.mcp_client`` tool
      3. write results to ``ft_strategy_runs`` and ``ft_strategy_events``
      4. mirror to ``HISTORY.jsonl`` via ``handshake.write_hyperopt_to_history``
      5. enqueue next stage on success

    For Phase 5 the worker is a stub that prints intended actions; it is
    exercised by integration smoke tests (Phase 6).
    """

    SUPPORTED_QUEUES: tuple[str, ...] = (
        "ft_strategy_create",
        "ft_hyperopt",
        "ft_backtest",
        "ft_analyze",
    )

    def __init__(self, *, dry_run: bool = True, redis_url: Optional[str] = None):
        self.dry_run = dry_run
        self.redis_url = redis_url or "redis://localhost:6379/0"

    def process(self, job: WorkerJob) -> WorkerResult:
        """Process a single job. Returns a structured result.

        Defense: returns a failed WorkerResult for non-WorkerJob input
        rather than raising (consistent with D-FT-23).
        """
        if not isinstance(job, WorkerJob):
            return WorkerResult(
                ok=False, queue="?", job_id="?",
                detail=f"job must be WorkerJob; got {type(job).__name__}",
            )
        if job.queue not in self.SUPPORTED_QUEUES:
            return WorkerResult(
                ok=False, queue=job.queue, job_id=job.job_id,
                detail=f"unknown queue: {job.queue}; supported={self.SUPPORTED_QUEUES}",
            )

        if self.dry_run:
            logger.info(
                "ft-strategy-worker (dry-run): queue=%s job_id=%s strategy=%s",
                job.queue, job.job_id, job.strategy_id,
            )
            return WorkerResult(ok=True, queue=job.queue, job_id=job.job_id)

        # Live mode — actual MCP call would go here. Phase 5+ work.
        return WorkerResult(
            ok=False,
            queue=job.queue,
            job_id=job.job_id,
            detail="live worker mode not implemented in Phase 5; set dry_run=True",
        )

    def queue_names(self) -> tuple[str, ...]:
        return self.SUPPORTED_QUEUES


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FT Strategy UI worker (Phase 5 stub)")
    p.add_argument("--queue", choices=FTStrategyWorker.SUPPORTED_QUEUES,
                   required=True, help="RQ queue to consume")
    p.add_argument("--job-id", required=True, help="Job ID to process")
    p.add_argument("--strategy-id", required=True, help="Strategy ID")
    p.add_argument("--payload-json", default="{}", help="JSON payload")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--live", dest="dry_run", action="store_false",
                   help="actually invoke MCP (NOT IMPLEMENTED in Phase 5)")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    try:
        payload = json.loads(args.payload_json)
    except json.JSONDecodeError as e:
        logger.error("bad payload JSON: %s", e)
        return 2

    worker = FTStrategyWorker(dry_run=args.dry_run)
    job = WorkerJob(
        queue=args.queue,
        job_id=args.job_id,
        strategy_id=args.strategy_id,
        payload=payload,
    )
    result = worker.process(job)

    print(json.dumps({
        "ok": result.ok,
        "queue": result.queue,
        "job_id": result.job_id,
        "detail": result.detail,
    }))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
