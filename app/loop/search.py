"""Search loop — 1+λ evolution strategy on top of the driver.

This module glues together:

* :mod:`app.loop.mutation`  — per-cluster mutators
* :mod:`app.loop.sensitivity` — σ calibration per field
* :mod:`app.loop.driver`    — fan-out + persistence

Each "generation":

1. Pick a cluster to mutate (round-robin or ε-greedy by recent regret).
2. Spawn λ=10 child candidates by mutating the current best at that
   cluster with sensitivity-scaled σ.
3. Fan them out via the driver subprocess (writes to HISTORY + PARETO).
4. Update the parent's known best from the Pareto front.

Safety rails (plan §3.4):

* ``timeout_per_candidate`` — hard wall-clock cap per candidate.
* ``max_diff_per_gen`` — at most N fields mutated per generation (we
  default to 1 — "mutate one cluster per generation").
* ``weekly_budget_usd`` — rough cost ceiling. Cost per candidate is
  estimated from elapsed_seconds × dollars_per_cpu_second (default $0).
  We default ``dollars_per_cpu_second=0`` because the v3 harness runs
  locally on the developer's CPU; the budget check is a no-op unless
  the operator sets a positive value.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.config.tuning import TUNING, TuningConstants, from_dict, to_dict
from app.loop import state
from app.loop.mutation import (
    DEFAULT_CLUSTER_MAP,
    all_clusters,
    mutate_cluster,
    mutate_field,
)
from app.loop.sensitivity import (
    SensitivityReport,
    load_report,
)

logger = logging.getLogger("app.loop.search")


@dataclass
class GenerationConfig:
    """Inputs to one :func:`run_generation` call."""

    gen: int
    parent_sha: str
    parent: TuningConstants
    cluster: str
    lambda_: int = 10
    sigma_scale: float = 1.0
    n_mutations: int = 1
    timeout_seconds: int = 900
    weekly_budget_usd: float = 0.0
    dollars_per_cpu_second: float = 0.0

    def estimate_cost(self, elapsed_seconds: float) -> float:
        return elapsed_seconds * self.dollars_per_cpu_second


@dataclass
class SafetyCheck:
    """One safety-rail verdict returned to the caller."""

    name: str
    ok: bool
    detail: str = ""


@dataclass
class GenerationResult:
    """Outcome of a generation (mirrors the driver's stdout + extras)."""

    gen: int
    cluster: str
    parent_sha: str
    candidates: list[dict] = field(default_factory=list)
    safety: list[SafetyCheck] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    skipped: bool = False
    skip_reason: str = ""

    @property
    def elapsed_seconds(self) -> float:
        return self.finished_at - self.started_at


# --- Safety rails ------------------------------------------------------------


def check_safety(
    cfg: GenerationConfig,
    *,
    weekly_spend_usd: float = 0.0,
) -> list[SafetyCheck]:
    """Run all the safety rails. Return a verdict list; ``ok=True`` means
    the generation may proceed."""
    checks: list[SafetyCheck] = []

    # 1) Diff size — at most n_mutations fields touched.
    checks.append(
        SafetyCheck(
            name="diff_size",
            ok=cfg.n_mutations <= 5,
            detail=f"n_mutations={cfg.n_mutations} (cap=5)",
        )
    )

    # 2) Timeout — at least 60s per candidate so slow but valid runs aren't
    # killed prematurely.
    checks.append(
        SafetyCheck(
            name="timeout_floor",
            ok=cfg.timeout_seconds >= 60,
            detail=f"timeout={cfg.timeout_seconds}s (floor=60)",
        )
    )

    # 3) Weekly budget — caller passes weekly_spend_usd so we don't have
    # to read it from a global state file.
    over_budget = cfg.weekly_budget_usd > 0 and weekly_spend_usd + cfg.lambda_ * 0.01 > cfg.weekly_budget_usd
    checks.append(
        SafetyCheck(
            name="weekly_budget",
            ok=not over_budget,
            detail=(f"spend={weekly_spend_usd:.2f} budget={cfg.weekly_budget_usd:.2f}"),
        )
    )

    # 4) Cluster exists.
    checks.append(
        SafetyCheck(
            name="cluster_exists",
            ok=cfg.cluster in DEFAULT_CLUSTER_MAP,
            detail=f"cluster={cfg.cluster!r}",
        )
    )

    return checks


# --- Generation runner -------------------------------------------------------


def make_child_candidates(
    parent: TuningConstants,
    cluster: str,
    *,
    lambda_: int,
    sigma_scale: float,
    n_mutations: int,
    gen: int,
    sensitivity: Optional[SensitivityReport] = None,
    seed: int | None = None,
) -> list[dict]:
    """Generate λ child TuningConstants dicts ready for the driver.

    When ``sensitivity`` is None we use the blanket ``sigma_scale`` and
    call ``mutate_cluster`` once. When it is provided we instead pick
    ``n_mutations`` random fields in the cluster and perturb each with
    its per-field σ from the report. The two paths are kept separate so
    we never double-mutate a field.
    """
    rng = random.Random(seed)
    members = DEFAULT_CLUSTER_MAP[cluster]
    children: list[dict] = []
    for i in range(lambda_):
        if sensitivity is None:
            child = mutate_cluster(
                parent,
                cluster,
                rng=rng,
                sigma_scale=sigma_scale,
                n_mutations=n_mutations,
            )
        else:
            chosen = rng.sample(members, min(n_mutations, len(members)))
            child = parent
            for name, kind, kwargs in chosen:
                scale = sensitivity.scale_for(name)
                child = mutate_field(name, kind, kwargs, child, rng, sigma_scale=scale)
        children.append(
            {
                "candidate_id": f"gen{gen}-{cluster.replace(' ', '')}-{i:03d}",
                "tuning": to_dict(child),
            }
        )
    return children


def run_generation(
    cfg: GenerationConfig,
    *,
    state_root: Path,
    sensitivity: Optional[SensitivityReport] = None,
    weekly_spend_usd: float = 0.0,
    driver_cmd: list[str] | None = None,
    symbol_set: str = "BTCUSD,ETHUSD,SOLUSD",
    quarter: str | None = None,
    seed: int | None = None,
) -> GenerationResult:
    """Run one generation end-to-end.

    ``driver_cmd`` lets the caller inject a stubbed driver (e.g. in tests)
    instead of actually invoking the v3 harness. Each candidate becomes a
    record in :attr:`GenerationResult.candidates` shaped like a
    :class:`app.loop.worker.CandidateResult`.

    The function does NOT call the driver subprocess itself — it writes a
    ``candidates.json`` under ``loop_state/`` and returns. The driver is
    a separate process so that one operator can run them in series (or
    in parallel with multiple operators on different machines).
    """
    result = GenerationResult(
        gen=cfg.gen,
        cluster=cfg.cluster,
        parent_sha=cfg.parent_sha,
        started_at=time.time(),
    )
    result.safety = check_safety(cfg, weekly_spend_usd=weekly_spend_usd)
    if not all(c.ok for c in result.safety):
        result.skipped = True
        result.skip_reason = "; ".join(f"{c.name}: {c.detail}" for c in result.safety if not c.ok)
        result.finished_at = time.time()
        logger.warning("generation skipped: %s", result.skip_reason)
        return result

    children = make_child_candidates(
        cfg.parent,
        cfg.cluster,
        lambda_=cfg.lambda_,
        sigma_scale=cfg.sigma_scale,
        n_mutations=cfg.n_mutations,
        gen=cfg.gen,
        sensitivity=sensitivity,
        seed=seed,
    )

    # Persist the candidates file the driver will read.
    state_root = state.ensure_root(state_root)
    cand_path = state_root / "next_generation.json"
    cand_payload = {
        "gen": cfg.gen,
        "cluster": cfg.cluster,
        "symbol_set": symbol_set,
        "quarter": quarter,
        "candidates": children,
    }
    cand_path.write_text(json.dumps(cand_payload, indent=2))

    result.candidates = children
    result.finished_at = time.time()
    logger.info(
        "gen=%d cluster=%s candidates=%d -> %s",
        cfg.gen,
        cfg.cluster,
        len(children),
        cand_path,
    )
    return result


# --- CLI driver --------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description="Generate one loop generation")
    p.add_argument("--parent-yaml", default=None, help="YAML/JSON file with TuningConstants; defaults to TUNING")
    p.add_argument("--state-root", default=str(state.DEFAULT_ROOT))
    p.add_argument("--gen", type=int, default=1)
    p.add_argument("--cluster", choices=all_clusters(), default="C1 Geometry")
    p.add_argument("--lambda", dest="lambda_", type=int, default=10)
    p.add_argument("--sigma-scale", type=float, default=1.0)
    p.add_argument("--n-mutations", type=int, default=1)
    p.add_argument("--sensitivity", default=None, help="Optional sensitivity.json for per-field σ scaling")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--weekly-budget", type=float, default=0.0)
    p.add_argument("--dollars-per-cpu-second", type=float, default=0.0)
    p.add_argument("--quarter", default=None)
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.parent_yaml:
        parent = from_dict(json.loads(Path(args.parent_yaml).read_text()))
    else:
        parent = TUNING

    sensitivity = None
    if args.sensitivity:
        sensitivity = load_report(Path(args.sensitivity))

    cfg = GenerationConfig(
        gen=args.gen,
        parent_sha=state.params_sha(parent),
        parent=parent,
        cluster=args.cluster,
        lambda_=args.lambda_,
        sigma_scale=args.sigma_scale,
        n_mutations=args.n_mutations,
        timeout_seconds=args.timeout,
        weekly_budget_usd=args.weekly_budget,
        dollars_per_cpu_second=args.dollars_per_cpu_second,
    )
    res = run_generation(
        cfg,
        state_root=Path(args.state_root),
        sensitivity=sensitivity,
        quarter=args.quarter,
        seed=args.seed,
    )
    print(
        json.dumps(
            {
                "gen": res.gen,
                "cluster": res.cluster,
                "parent_sha": res.parent_sha,
                "skipped": res.skipped,
                "skip_reason": res.skip_reason,
                "n_candidates": len(res.candidates),
                "candidates_path": str(Path(args.state_root) / "next_generation.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
