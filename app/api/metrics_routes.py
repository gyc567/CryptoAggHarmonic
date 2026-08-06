"""Prometheus metrics endpoint for loop observability.

Mounted at /metrics via the Flask app factory.
Requires prometheus_client to be installed.

Metrics exposed:
- tuning_proposals_total{decision}
- loop_generation_duration_seconds
- llm_maker_calls_total
- llm_checker_calls_total
- llm_tokens_total{type}
- llm_latency_seconds
- llm_cost_usd_total
- pareto_front_size
- mc_agreement_rate
- suspicious_to_human_rate
- worker_timeout_total
- runs_disk_bytes
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Blueprint, Response

logger = logging.getLogger(__name__)

# Try to use prometheus_client; if not installed, return empty metrics
try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        REGISTRY,
    )
    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False
    logger.warning("prometheus_client not installed; /metrics endpoint will return empty response")


# --- Metric definitions (created lazily) ---

_metrics: dict = {}


def _init_metrics():
    """Initialize all metrics. Called once on first request."""
    if not HAS_PROMETHEUS:
        return

    global _metrics
    if _metrics:
        return  # already initialized

    _metrics = {
        "tuning_proposals_total": Counter(
            "tuning_proposals_total",
            "Total tuning proposals",
            ["decision"],
        ),
        "loop_generation_duration_seconds": Histogram(
            "loop_generation_duration_seconds",
            "Generation duration in seconds",
            buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600],
        ),
        "llm_maker_calls_total": Counter(
            "llm_maker_calls_total",
            "Total Maker LLM calls",
        ),
        "llm_checker_calls_total": Counter(
            "llm_checker_calls_total",
            "Total Checker LLM calls",
        ),
        "llm_tokens_total": Counter(
            "llm_tokens_total",
            "Total LLM tokens",
            ["type"],  # input or output
        ),
        "llm_latency_seconds": Histogram(
            "llm_latency_seconds",
            "LLM call latency",
            buckets=[0.1, 0.25, 0.5, 1, 2, 5, 10, 30],
        ),
        "llm_cost_usd_total": Counter(
            "llm_cost_usd_total",
            "Total LLM cost in USD",
        ),
        "llm_cache_hit_total": Counter(
            "llm_cache_hit_total",
            "LLM cache hits",
        ),
        "pareto_front_size": Gauge(
            "pareto_front_size",
            "Current Pareto front size",
        ),
        "mc_agreement_rate": Gauge(
            "mc_agreement_rate",
            "Maker-Checker agreement rate (rolling average)",
        ),
        "suspicious_to_human_rate": Gauge(
            "suspicious_to_human_rate",
            "Rate of suspicious_to_human verdicts",
        ),
        "worker_timeout_total": Counter(
            "worker_timeout_total",
            "Worker timeouts",
        ),
        "runs_disk_bytes": Gauge(
            "runs_disk_bytes",
            "Total disk usage of runs/ directory in bytes",
        ),
        "loop_readiness_score": Gauge(
            "loop_readiness_score",
            "Current Loop Readiness Score",
        ),
    }


def make_metrics_blueprint() -> Blueprint:
    """Create the /metrics blueprint."""
    bp = Blueprint("metrics", __name__)

    @bp.route("/metrics")
    def metrics() -> Response:
        _init_metrics()

        if not HAS_PROMETHEUS:
            # Return a minimal metrics response when prometheus_client not installed
            return Response(
                "# prometheus_client not installed\n",
                mimetype="text/plain",
            )

        # Update dynamic gauges before generating
        _update_dynamic_gauges()

        return Response(
            generate_latest(REGISTRY),
            mimetype=CONTENT_TYPE_LATEST,
        )

    return bp


def _update_dynamic_gauges():
    """Update gauges that depend on current state."""
    if not _metrics:
        return

    # Pareto front size
    try:
        from app.loop.pareto import load as pareto_load
        from app.loop.state import DEFAULT_ROOT
        import os

        pareto_path = Path(os.environ.get("LOOP_STATE_ROOT", str(DEFAULT_ROOT))) / "PARETO.json"
        if pareto_path.exists():
            pareto = pareto_load(pareto_path)
            _metrics["pareto_front_size"].set(len(pareto))
    except Exception:
        pass

    # Runs disk usage
    try:
        import os
        runs_path = Path(os.environ.get("LOOP_STATE_ROOT", str(DEFAULT_ROOT))) / "runs"
        if runs_path.exists():
            total = sum(
                f.stat().st_size
                for f in runs_path.rglob("*")
                if f.is_file()
            )
            _metrics["runs_disk_bytes"].set(total)
    except Exception:
        pass


# --- Convenience helpers for internal use ---


def record_proposal(decision: str) -> None:
    """Record a tuning proposal decision."""
    _init_metrics()
    if "tuning_proposals_total" in _metrics:
        _metrics["tuning_proposals_total"].labels(decision=decision).inc()


def record_llm_call(call_type: str, tokens: int = 0, latency: float = 0.0, cost: float = 0.0) -> None:
    """Record an LLM call."""
    _init_metrics()
    if not _metrics:
        return
    if call_type == "maker":
        _metrics["llm_maker_calls_total"].inc()
    elif call_type == "checker":
        _metrics["llm_checker_calls_total"].inc()
    if tokens > 0:
        _metrics["llm_tokens_total"].labels(type="input").inc(tokens // 2)
        _metrics["llm_tokens_total"].labels(type="output").inc(tokens // 2)
    if latency > 0:
        _metrics["llm_latency_seconds"].observe(latency)
    if cost > 0:
        _metrics["llm_cost_usd_total"].inc(cost)


def record_generation(duration_seconds: float) -> None:
    """Record a generation completion."""
    _init_metrics()
    if "loop_generation_duration_seconds" in _metrics:
        _metrics["loop_generation_duration_seconds"].observe(duration_seconds)
