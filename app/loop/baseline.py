"""Phase 0 baseline helpers — generate candidates + optional dry-run gen.

Real multi-hour backtests need market data under ``data/backtest/`` and
``.scratch/backtest/run_backtest_v3.py``. Until then, use
``LOOP_WORKER_DRY_RUN=1`` to smoke the driver → HISTORY / PARETO / STATE path.

Usage::

    # Pipeline smoke (synthetic metrics)
    LOOP_WORKER_DRY_RUN=1 python -m app.loop.baseline --n 20 --run

    # Emit candidates JSON only (for a real harness run later)
    python -m app.loop.baseline --n 20 --out candidates-baseline.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from app.config.tuning import TUNING, to_dict
from app.loop import state
from app.loop.mutation import all_clusters, mutate_cluster

logger = logging.getLogger("app.loop.baseline")


def build_baseline_candidates(
    n: int = 20,
    *,
    gen: int = 0,
    cluster: str | None = None,
    seed: int = 0,
    symbol_set: str = "BTCUSD",
) -> dict[str, Any]:
    """Build a candidates payload for :mod:`app.loop.driver`.

    Candidate 0 is the current ``TUNING`` singleton (unmutated baseline).
    Remaining candidates are single-cluster mutations with increasing σ.
    """
    import random

    cluster = cluster or all_clusters()[0]
    rng = random.Random(seed)
    candidates: list[dict[str, Any]] = []

    # Baseline (parent) as candidate 0
    candidates.append(
        {
            "candidate_id": f"baseline-{gen:03d}-000",
            "tuning": to_dict(TUNING),
        }
    )

    for i in range(1, n):
        sigma = 0.5 + (i / max(n - 1, 1)) * 1.5
        child = mutate_cluster(TUNING, cluster, rng, sigma_scale=sigma)
        candidates.append(
            {
                "candidate_id": f"baseline-{gen:03d}-{i:03d}",
                "tuning": to_dict(child),
            }
        )

    return {
        "gen": gen,
        "cluster": cluster,
        "symbol_set": symbol_set,
        "quarter": None,
        "candidates": candidates,
        "meta": {
            "phase": 0,
            "purpose": "baseline",
            "seed": seed,
            "n": n,
        },
    }


def write_candidates(payload: dict[str, Any], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    return path


def summarize_state_root(state_root: Path) -> dict[str, Any]:
    """Collect Phase 0 acceptance metrics from a state root."""
    root = Path(state_root)
    history = root / "HISTORY.jsonl"
    pareto = root / "PARETO.json"
    state_md = root / "STATE.md"

    n_history = 0
    decisions: dict[str, int] = {}
    fitnesses: list[float] = []
    if history.exists():
        for line in history.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            n_history += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            d = rec.get("decision") or "unknown"
            decisions[d] = decisions.get(d, 0) + 1
            if rec.get("fitness") is not None:
                fitnesses.append(float(rec["fitness"]))

    pareto_size = 0
    if pareto.exists():
        try:
            data = json.loads(pareto.read_text())
            # Pareto file may be list or {"points": [...]}
            if isinstance(data, list):
                pareto_size = len(data)
            elif isinstance(data, dict):
                pareto_size = len(data.get("points") or data.get("front") or [])
        except json.JSONDecodeError:
            pass

    avg_fit = sum(fitnesses) / len(fitnesses) if fitnesses else None
    return {
        "history_records": n_history,
        "decisions": decisions,
        "pareto_size": pareto_size,
        "avg_fitness": avg_fit,
        "state_md_exists": state_md.exists(),
        "dry_run": os.environ.get("LOOP_WORKER_DRY_RUN") == "1",
    }


def run_baseline(
    *,
    n: int = 20,
    state_root: Path,
    workers: int = 2,
    seed: int = 0,
    candidates_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Generate candidates and invoke the driver main path in-process."""
    from app.loop import driver as driver_mod

    payload = build_baseline_candidates(n=n, seed=seed)
    cand_path = candidates_path or (Path(state_root) / "candidates-baseline.json")
    write_candidates(payload, cand_path)

    # Invoke driver via argv simulation
    argv = [
        "driver",
        "--candidates",
        str(cand_path),
        "--state-root",
        str(state_root),
        "--workers",
        str(workers),
        "--timeout",
        "120",
    ]
    old = sys.argv
    t0 = time.time()
    try:
        sys.argv = argv
        driver_mod.main()
    finally:
        sys.argv = old

    summary = summarize_state_root(state_root)
    summary["elapsed_seconds"] = round(time.time() - t0, 3)
    summary["candidates_path"] = str(cand_path)
    summary["state_root"] = str(state_root)
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 0 baseline generator / dry-run")
    p.add_argument("--n", type=int, default=20, help="Number of candidates (default 20)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=None, help="Write candidates JSON here")
    p.add_argument("--run", action="store_true", help="Run driver after generating candidates")
    p.add_argument(
        "--state-root",
        default=str(state.DEFAULT_ROOT / "phase0"),
        help="loop_state root for --run",
    )
    p.add_argument("--workers", type=int, default=2)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Set LOOP_WORKER_DRY_RUN=1 for synthetic metrics (pipeline smoke)",
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.dry_run:
        os.environ["LOOP_WORKER_DRY_RUN"] = "1"
        logger.info("LOOP_WORKER_DRY_RUN=1 (synthetic metrics — not a market baseline)")

    payload = build_baseline_candidates(n=args.n, seed=args.seed)
    out = Path(args.out) if args.out else Path(args.state_root) / "candidates-baseline.json"
    write_candidates(payload, out)
    print(f"wrote {len(payload['candidates'])} candidates → {out}")

    if not args.run:
        return 0

    summary = run_baseline(
        n=args.n,
        state_root=Path(args.state_root),
        workers=args.workers,
        seed=args.seed,
        candidates_path=out,
    )
    print(json.dumps(summary, indent=2))
    ok = summary["history_records"] >= min(args.n, 1) and summary["state_md_exists"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
