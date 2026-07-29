"""Single-generation loop driver.

Reads a list of candidates from a JSON file, fans them across a
``ProcessPoolExecutor``, persists each result under ``loop_state/runs/<uuid>/``,
appends to ``HISTORY.jsonl`` (fcntl-locked), updates ``PARETO.json`` if the
candidate is non-dominated, and re-renders ``STATE.md``.

JSON format for ``--candidates``::

    {
      "gen": 1,
      "cluster": "C3 Confluence",
      "candidates": [
        {"candidate_id": "gen1-001", "tuning": { ... TuningConstants fields ... }},
        ...
      ],
      "symbol_set": "BTCUSD,ETHUSD,SOLUSD",
      "quarter": null
    }

The driver is intentionally small. The CMA-ES search loop itself lives
in :mod:`app.loop.search` (M3) — this driver just glues workers + state
together so we can run a batch of candidates manually today.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from app.config.tuning import TUNING, from_dict, to_dict
from app.loop import state
from app.loop.checker import check_candidate
from app.loop.pareto import (
    ParetoSet,
    from_metrics,
    load as pareto_load,
    save as pareto_save,
)
from app.loop.skills_version import current_version
from app.loop.worker import CandidateResult, run_candidate


logger = logging.getLogger("app.loop.driver")


def _run_one(args: dict) -> CandidateResult:
    """Unpack and run a single candidate. Module-level so ProcessPoolExecutor
    can pickle the target (lambdas / closures don't pickle)."""
    return run_candidate(
        candidate_id=args["candidate_id"],
        tuning=args["tuning"],
        symbol_set=args["symbol_set"],
        quarter=args.get("quarter"),
        run_dir=args["run_dir"],
        anchor_step=args.get("anchor_step", 50),
        timeout_seconds=args.get("timeout_seconds", 900),
    )


def main():
    p = argparse.ArgumentParser(description="Single-generation loop driver")
    p.add_argument("--candidates", required=True,
                   help="JSON file with {gen, cluster, candidates[], symbol_set, quarter}")
    p.add_argument("--state-root", default=str(state.DEFAULT_ROOT),
                   help="loop_state root directory")
    p.add_argument("--workers", type=int, default=4,
                   help="ProcessPoolExecutor worker count")
    p.add_argument("--timeout", type=int, default=900,
                   help="Per-candidate subprocess timeout (seconds)")
    p.add_argument("--anchor-step", type=int, default=50)
    p.add_argument(
        "--use-maker-checker",
        action="store_true",
        help=(
            "Augment the M4 verdict with the Maker-Checker runner "
            "(LLM second opinion + arbitration). Disabled by default "
            "to preserve the v0 driver behaviour."
        ),
    )
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    with open(args.candidates) as f:
        cfg = json.load(f)

    gen = cfg.get("gen", 0)
    cluster = cfg.get("cluster", "?")
    symbol_set = cfg.get("symbol_set", "BTCUSD,ETHUSD,SOLUSD")
    quarter = cfg.get("quarter")
    candidates = cfg["candidates"]
    state_root = state.ensure_root(Path(args.state_root))

    # Per-candidate jobs.
    jobs: list[dict] = []
    for c in candidates:
        run_dir = state.make_run_dir(state_root)
        jobs.append({
            "candidate_id": c["candidate_id"],
            "tuning": c["tuning"],
            "symbol_set": symbol_set,
            "quarter": quarter,
            "run_dir": run_dir,
            "anchor_step": args.anchor_step,
            "timeout_seconds": args.timeout,
        })

    logger.info(
        "gen=%d cluster=%s candidates=%d workers=%d quarter=%s",
        gen, cluster, len(jobs), args.workers, quarter or "full",
    )

    # Optional Maker-Checker runner. Created lazily so the v0 driver
    # behaviour is preserved when ``--use-maker-checker`` is absent.
    mc_runner: Optional[Any] = None
    if args.use_maker_checker:
        from app.loop.maker_checker.adapter import evaluate_candidate  # noqa: F401
        from app.loop.maker_checker.runner import make_runner

        mc_runner = make_runner()
        logger.info("Maker-Checker runner attached")
        if not mc_runner.enabled:
            # Audit §2.9: env disabled the runner that the CLI asked
            # for. Surface the inconsistency loudly so the operator
            # either unsets the env or drops the flag.
            logger.warning(
                "MAKER_CHECKER_ENABLED=false but --use-maker-checker was "
                "passed; runner will short-circuit to M4-only verdicts",
            )

    # Fan out.
    results: list[CandidateResult] = []
    if not jobs:
        logger.warning("no candidates; nothing to do")
    else:
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=args.workers,
        ) as pool:
            futures = {
                pool.submit(_run_one, j): j["candidate_id"]
                for j in jobs
            }
            for fut in concurrent.futures.as_completed(futures):
                cid = futures[fut]
                try:
                    r = fut.result()
                except Exception as exc:
                    r = CandidateResult(
                        candidate_id=cid, params_sha="?", cluster=cluster,
                        gen=gen, decision="error",
                        error=f"worker raised: {exc!r}",
                    )
                r.cluster = cluster
                r.gen = gen
                results.append(r)
                logger.info(
                    "candidate=%s decision=%s sha=%s fitness=%s",
                    cid, r.decision, r.params_sha[:8],
                    f"{r.fitness:+.3f}" if r.fitness is not None else "—",
                )

    # Update durable state.
    pareto_path = state_root / "PARETO.json"
    pareto = pareto_load(pareto_path)

    skills_version = current_version()

    accepted_count = 0
    rejected_count = 0
    error_count = 0
    best_so_far: Optional[CandidateResult] = None

    for r in results:
        # Run the second-opinion checker (plan §4). When a Maker-Checker
        # runner is attached we use the adapter so the M4 verdict can
        # be overruled by the LLM check (audit §2.5). Otherwise we use
        # the existing ``check_candidate`` exactly as before.
        if mc_runner is not None:
            from app.loop.maker_checker.adapter import evaluate_candidate

            verdict = evaluate_candidate(r, runner=mc_runner)
        else:
            verdict = check_candidate(r, parent_metrics=None)

        # Append to HISTORY regardless of decision. Tag every record
        # with the skills_version so we can detect stale decisions.
        state.append_history({
            "ts": time.time(),
            "gen": gen,
            "cluster": cluster,
            "candidate_id": r.candidate_id,
            "params_sha": r.params_sha,
            "decision": r.decision,
            "rejection_reason": r.rejection_reason,
            "fitness": r.fitness,
            "metrics": r.metrics,
            "run_dir": r.run_dir,
            "error": r.error,
            "checker": {
                "decision": verdict.decision,
                "confidence": verdict.confidence,
                "reasons": verdict.reasons,
                "flags": verdict.flags,
            },
            "skills_version": skills_version,
        }, root=state_root)

        if r.decision == "accepted":
            accepted_count += 1
            point = from_metrics(
                metrics=r.metrics, params_sha=r.params_sha,
                gen=gen, cluster=cluster, run_dir=r.run_dir,
                fitness=r.fitness or 0.0,
            )
            moved = pareto.add(point)
            if moved:
                # Snap the tuning so the user can recover it.
                with open(Path(r.run_dir) / "tuning.yaml") as f:
                    payload = f.read()
                (state_root / "tuning_snapshots" /
                 f"pareto-{point.params_sha}.yaml").write_text(payload)
            if best_so_far is None or (r.fitness or 0) > (best_so_far.fitness or 0):
                best_so_far = r
        elif r.decision == "rejected":
            rejected_count += 1
            # Move rejected runs under REJECTED/<reason>/ for inspection.
            reason = (r.rejection_reason or "unknown").replace(" ", "_")
            dest = state_root / "REJECTED" / reason / Path(r.run_dir).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(r.run_dir, dest)
            except OSError:
                pass
        elif r.decision == "error":
            error_count += 1
            dest = state_root / "REJECTED" / "errors" / Path(r.run_dir).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(r.run_dir, dest)
            except OSError:
                pass

    pareto_save(pareto_path, pareto)

    # Update STATE.md.
    best_dict = None
    if best_so_far is not None:
        best_dict = {
            "params_sha": best_so_far.params_sha,
            "gen": best_so_far.gen,
            "fitness": best_so_far.fitness or 0.0,
            "sharpe": best_so_far.metrics.get("sharpe") or 0.0,
            "calmar": best_so_far.metrics.get("calmar") or 0.0,
            "profit_factor": best_so_far.metrics.get("profit_factor") or 0.0,
            "trade_count": best_so_far.metrics.get("trades_count", 0),
        }
    state.write_state_md(
        state.render_state_md(
            best=best_dict,
            pareto_size=len(pareto),
            plateau_count=0,
            next_queue_size=0,
            last_decision=(
                f"accepted={accepted_count} rejected={rejected_count} "
                f"errors={error_count}"
            ),
            notes=[
                f"cluster: {cluster}",
                f"symbol_set: {symbol_set}",
                f"quarter: {quarter or 'full'}",
                f"skills_version: {skills_version}",
            ],
        ),
        root=state_root,
    )

    logger.info(
        "done: %d accepted, %d rejected, %d errors, pareto=%d",
        accepted_count, rejected_count, error_count, len(pareto),
    )


if __name__ == "__main__":
    main()