"""binance market data — prometheus-style metrics.

Tiny hand-rolled counter / histogram store. No external dependency.
Exposed via ``/metrics`` by the Flask ``metrics_routes.py`` blueprint.

ponytail: 30 lines instead of pulling in ``prometheus_client``. The
project already uses an in-tree CollectorRegistry in
``app/api/metrics_routes.py``; adding a second one here would duplicate
the pattern. A future refactor can swap to ``prometheus_client`` if
this becomes a bottleneck (it won't — these counters are incremented
once per REST call).

Counts / histograms tracked:

  - ``binance_market_fetch_total{endpoint, status}`` — Counter
  - ``binance_market_latency_seconds{endpoint}`` — Histogram

Endpoints: ``mark_price``, ``open_interest``, ``funding_history``.
Statuses: ``ok``, ``timeout``, ``json_error``, ``cli_error``.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Mapping

# Histogram bucket boundaries (seconds). Match the LOOP.md §7.2 bucket
# scheme so the /metrics output is consistent across the project.
_LATENCY_BUCKETS: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)


class _Metrics:
    """Thread-safe counter + histogram registry.

    The Flask app is multi-threaded (gunicorn workers × threads), so
    every mutation is guarded by a lock. Reads (``snapshot()``) take
    the lock too; they're infrequent (once per ``/metrics`` scrape).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Counter: endpoint × status → count
        self._counter: dict[tuple[str, str], int] = defaultdict(int)
        # Histogram: endpoint → list of bucket counts (parallel to
        # _LATENCY_BUCKETS) + count + sum
        self._hist: dict[str, list[float]] = {}

    def inc(self, endpoint: str, status: str) -> None:
        with self._lock:
            self._counter[(endpoint, status)] += 1

    def observe(self, endpoint: str, latency_s: float) -> None:
        with self._lock:
            hist = self._hist.setdefault(
                endpoint,
                [0.0] * (len(_LATENCY_BUCKETS) + 2),  # buckets + count + sum
            )
            for i, bound in enumerate(_LATENCY_BUCKETS):
                if latency_s <= bound:
                    hist[i] += 1
            hist[-2] += 1.0          # count
            hist[-1] += latency_s    # sum

    def snapshot(self) -> Mapping[str, object]:
        """Return a copy of the current state for ``/metrics`` scraping."""
        with self._lock:
            counter = dict(self._counter)
            hist = {endpoint: list(buckets) for endpoint, buckets in self._hist.items()}
        return {
            "counter": counter,
            "histogram_buckets_s": list(_LATENCY_BUCKETS),
            "histogram": hist,
        }


# Module-level singleton. Tests can call ``reset()`` to start clean.
_metrics = _Metrics()


def record_fetch(endpoint: str, status: str, latency_s: float) -> None:
    """One-shot helper called by ``data_source._run_cli`` (or its caller)."""
    _metrics.inc(endpoint, status)
    _metrics.observe(endpoint, latency_s)


def get_snapshot() -> Mapping[str, object]:
    """Return the current metrics snapshot for ``/metrics`` exposure."""
    return _metrics.snapshot()


def reset() -> None:
    """Reset all counters. Tests only."""
    global _metrics
    _metrics = _Metrics()