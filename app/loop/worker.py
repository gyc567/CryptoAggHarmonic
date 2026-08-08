"""Worker process — run one candidate through the v3 backtest harness.

Designed for ``concurrent.futures.ProcessPoolExecutor``. The entry point is
:func:`run_candidate` which takes a :class:`TuningConstants` (or a dict
rebuilt via :func:`app.config.tuning.from_dict`), a symbol set, optional
quarter, and a run directory. It writes ``tuning.yaml`` + ``backtest.log``
+ ``metrics.json`` (atomic rename) under the run directory and returns a
serialisable result record.

Why ProcessPool over ThreadPool: pandas / numpy release the GIL, so we
get true parallelism, and each worker has its own interpreter so the
hot-swap in :mod:`app.config.tuning` doesn't bleed across candidates.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.config.tuning import TuningConstants, from_dict, to_dict
from app.loop.state import params_sha

# --- Result record -----------------------------------------------------------


@dataclass
class CandidateResult:
    """Serialisable outcome of one candidate run."""

    candidate_id: str
    params_sha: str
    cluster: str
    gen: int
    decision: str  # "accepted" | "rejected" | "duplicate" | "error"
    rejection_reason: Optional[str] = None
    metrics: dict = field(default_factory=dict)
    fitness: Optional[float] = None
    run_dir: str = ""
    elapsed_seconds: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# --- Worker entry point ------------------------------------------------------


def run_candidate(
    candidate_id: str,
    tuning: TuningConstants | dict,
    *,
    symbol_set: str,
    quarter: Optional[str],
    run_dir: Path,
    anchor_step: int = 50,
    timeout_seconds: int = 900,
) -> CandidateResult:
    """Run the v3 harness on one candidate and persist artifacts.

    Returns a :class:`CandidateResult`. Failure modes map to:
    * ``decision="rejected"`` — the backtest ran but metrics rejected the
      candidate (e.g. trade count too low). ``metrics`` is populated.
    * ``decision="error"`` — the subprocess raised / timed out / produced
      no metrics.json. ``error`` carries the message.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(tuning, dict):
        tuning = from_dict(tuning)

    sha = params_sha(tuning)
    started = time.time()

    # Persist the tuning snapshot the worker actually used (debugging).
    tuning_path = run_dir / "tuning.yaml"
    payload = to_dict(tuning)
    lines = [f"{k}: {_yaml_scalar(v)}" for k, v in payload.items()]
    tuning_path.write_text("\n".join(lines) + "\n")

    log_path = run_dir / "backtest.log"

    # Dry-run: skip the real harness (Phase 0 pipeline smoke / CI).
    # Set LOOP_WORKER_DRY_RUN=1. Not a fitness baseline — synthetic metrics only.
    if os.environ.get("LOOP_WORKER_DRY_RUN") == "1":
        return _dry_run_result(
            candidate_id=candidate_id,
            sha=sha,
            run_dir=run_dir,
            started=started,
            log_path=log_path,
        )

    cmd = [
        sys.executable,
        ".scratch/backtest/run_backtest_v3.py",
        "--symbol-set",
        symbol_set,
        "--anchor-step",
        str(anchor_step),
        "--out-dir",
        str(run_dir),
    ]
    if quarter:
        cmd.extend(["--quarter", quarter])
    cmd.extend(["--tuning-yaml", str(tuning_path)])

    env = dict(os.environ)
    # Ensure the repo root is on PYTHONPATH inside the subprocess even if it
    # was launched from somewhere unusual.
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")

    try:
        proc = subprocess.run(  # noqa: S603  — sys.executable + list args, shell=False implicit
            cmd,
            cwd=repo_root,
            env=env,
            stdout=open(log_path, "wb"),
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CandidateResult(
            candidate_id=candidate_id,
            params_sha=sha,
            cluster="?",
            gen=-1,
            decision="error",
            run_dir=str(run_dir),
            elapsed_seconds=time.time() - started,
            error=f"subprocess timed out after {timeout_seconds}s: {exc}",
        )

    # Resolve the metrics file AFTER the subprocess ran — the v3 harness
    # writes ``summary.json``; some earlier harnesses wrote ``metrics.json``.
    metrics_path = run_dir / "summary.json"
    if not metrics_path.exists():
        metrics_path = run_dir / "metrics.json"

    if proc.returncode != 0 or not metrics_path.exists():
        return CandidateResult(
            candidate_id=candidate_id,
            params_sha=sha,
            cluster="?",
            gen=-1,
            decision="error",
            run_dir=str(run_dir),
            elapsed_seconds=time.time() - started,
            error=(f"subprocess exit={proc.returncode}, " f"metrics.json exists={metrics_path.exists()}"),
        )

    with open(metrics_path) as f:
        summary = json.load(f)

    agg = summary.get("__aggregate__", {})
    exp = agg.get("experimental", {})
    fitness = summary.get("__meta__", {}).get("fitness", {}).get("experimental")

    # Reject if trade count < 30 (loop-tuning plan §3 trade-count floor).
    tc = exp.get("trades_count", 0)
    if tc < 30:
        return CandidateResult(
            candidate_id=candidate_id,
            params_sha=sha,
            cluster="?",
            gen=-1,
            decision="rejected",
            rejection_reason=f"trades_count={tc} < 30",
            metrics=exp,
            fitness=fitness,
            run_dir=str(run_dir),
            elapsed_seconds=time.time() - started,
        )

    return CandidateResult(
        candidate_id=candidate_id,
        params_sha=sha,
        cluster="?",
        gen=-1,
        decision="accepted",
        metrics=exp,
        fitness=fitness,
        run_dir=str(run_dir),
        elapsed_seconds=time.time() - started,
    )


def _dry_run_result(
    *,
    candidate_id: str,
    sha: str,
    run_dir: Path,
    started: float,
    log_path: Path,
) -> CandidateResult:
    """Synthetic metrics for pipeline smoke (LOOP_WORKER_DRY_RUN=1).

    Deterministic-ish fitness from params_sha so Pareto still moves a little.
    """
    # Map last hex nibble → fitness in [0.5, 2.0]
    nibble = int(sha[-1], 16) if sha and sha[-1] in "0123456789abcdef" else 8
    fitness = 0.5 + (nibble / 15.0) * 1.5
    trades = 30 + nibble
    metrics = {
        "trades_count": trades,
        "sharpe": round(0.2 + nibble * 0.05, 4),
        "calmar": round(0.5 + nibble * 0.1, 4),
        "profit_factor": round(1.2 + nibble * 0.05, 4),
        "by_regime": {
            "bull": {"n": trades // 2, "sharpe": 0.3},
            "bear": {"n": trades // 3, "sharpe": 0.1},
            "range": {"n": max(1, trades // 6), "sharpe": 0.0},
        },
    }
    summary = {
        "__aggregate__": {"experimental": metrics},
        "__meta__": {"fitness": {"experimental": fitness}, "dry_run": True},
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    log_path.write_text(f"dry_run candidate={candidate_id} sha={sha} fitness={fitness}\n")
    return CandidateResult(
        candidate_id=candidate_id,
        params_sha=sha,
        cluster="?",
        gen=-1,
        decision="accepted",
        metrics=metrics,
        fitness=fitness,
        run_dir=str(run_dir),
        elapsed_seconds=time.time() - started,
    )


def _yaml_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return str(v)
    if isinstance(v, list | tuple):
        return "[" + ", ".join(_yaml_scalar(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_yaml_scalar(val)}" for k, val in v.items()) + "}"
    if isinstance(v, str):
        return json.dumps(v)
    return str(v)


# Module-level logger for the driver.
logger = logging.getLogger("app.loop.worker")
