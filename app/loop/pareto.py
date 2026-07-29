"""Pareto-front maintenance over the loop's multi-objective metrics.

Objectives (all "maximise"):

* ``sharpe``        — risk-adjusted return
* ``calmar``        — return / max drawdown (None → -inf)
* ``profit_factor`` — gross wins / gross losses (None → 0)
* ``worst_regime_sharpe`` — minimum per-regime sharpe, ties broken here

A candidate is **admitted** to the Pareto set iff no existing member
dominates it on every objective. A dominated candidate is rejected even
if it improves one objective (the user / reviewer chooses from the front
with full visibility).

The frontier is kept on disk as :class:`ParetoSet` JSON-serialisable
records with full provenance (params_sha, gen, run_dir) so the driver can
rehydrate a snapshot after a crash.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from app.loop.state import atomic_write_json


@dataclass
class ParetoPoint:
    """One entry on the Pareto front."""

    params_sha: str
    gen: int
    cluster: str
    run_dir: str
    sharpe: Optional[float]
    calmar: Optional[float]
    profit_factor: Optional[float]
    worst_regime_sharpe: Optional[float]
    trade_count: int
    fitness: float


def _safe(x: Optional[float], default: float) -> float:
    """Treat None as a worst-case value so a missing metric doesn't dominate."""
    return x if x is not None else default


def objectives(p: ParetoPoint) -> tuple[float, float, float, float]:
    """Maximise all four."""
    return (
        _safe(p.sharpe, -10.0),
        _safe(p.calmar, -10.0),
        _safe(p.profit_factor, 0.0),
        _safe(p.worst_regime_sharpe, -10.0),
    )


def dominates(a: ParetoPoint, b: ParetoPoint) -> bool:
    """True iff ``a`` is at least as good as ``b`` on every objective AND
    strictly better on at least one. Standard Pareto dominance."""
    oa = objectives(a)
    ob = objectives(b)
    all_ge = all(x >= y for x, y in zip(oa, ob))
    any_gt = any(x > y for x, y in zip(oa, ob))
    return all_ge and any_gt


@dataclass
class ParetoSet:
    """Mutable collection with dedupe + dominance pruning."""

    points: list[ParetoPoint] = field(default_factory=list)

    def add(self, p: ParetoPoint) -> bool:
        """Insert ``p`` if it isn't dominated by anyone and isn't already
        present (by ``params_sha``). Removes any existing members that
        ``p`` dominates. Returns True iff the front moved."""
        # Dedupe — same SHA = same experiment.
        if any(q.params_sha == p.params_sha for q in self.points):
            return False
        # Drop anyone p dominates.
        new_points = [q for q in self.points if not dominates(p, q)]
        # Only admit if p is not dominated by any survivor.
        if any(dominates(q, p) for q in new_points):
            return False
        new_points.append(p)
        self.points = new_points
        return True

    def __len__(self) -> int:
        return len(self.points)

    def __iter__(self):
        return iter(self.points)


def load(path: Path) -> ParetoSet:
    """Load a ParetoSet from a JSON file. Empty file ⇒ empty set."""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return ParetoSet()
    with open(path) as f:
        raw = json.load(f)
    return ParetoSet(points=[ParetoPoint(**r) for r in raw.get("points", [])])


def save(path: Path, ps: ParetoSet) -> None:
    atomic_write_json(
        path,
        {"points": [asdict(p) for p in ps.points]},
    )


def worst_regime_sharpe(metrics: dict) -> Optional[float]:
    """Extract the minimum per-regime sharpe from the v3 metrics blob."""
    regimes = metrics.get("by_regime", {})
    sharpes = [
        b["sharpe"] for b in regimes.values()
        if b.get("n", 0) >= 3 and b.get("sharpe") is not None
    ]
    if not sharpes:
        return None
    return min(sharpes)


def from_metrics(
    *,
    metrics: dict,
    params_sha: str,
    gen: int,
    cluster: str,
    run_dir: str,
    fitness: float,
) -> ParetoPoint:
    return ParetoPoint(
        params_sha=params_sha,
        gen=gen,
        cluster=cluster,
        run_dir=run_dir,
        sharpe=metrics.get("sharpe"),
        calmar=metrics.get("calmar"),
        profit_factor=metrics.get("profit_factor"),
        worst_regime_sharpe=worst_regime_sharpe(metrics),
        trade_count=metrics.get("trades_count", 0),
        fitness=fitness,
    )