from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from app.loop import state
from app.loop.worker import run_candidate

# --- Quarter discovery -------------------------------------------------------


"""Walk-forward quarterly validation.

Plan §7 specifies a 4-quarter rolling walk-forward: for each candidate
the loop should evaluate it on each of 4 consecutive quarters and only
admit it to the Pareto front if the OOS (out-of-sample) quarter is
consistent with the in-sample quarters.

This module:

* discovers the available quarters from a backtest metrics blob
* runs the v3 harness on each quarter (via :mod:`app.loop.worker`)
* aggregates per-quarter metrics into walk-forward aggregates
* flags candidates where OOS performance collapses

The actual subprocess invocation lives in :mod:`app.loop.worker`. This
module owns the orchestration + aggregation only, which makes it easy
to unit-test without spinning up the harness.
"""


def list_quarters(start_year: int = 2024, n_quarters: int = 8) -> list[str]:
    """Return the canonical ``YYYY-Qq`` list used by the v3 harness.

    Default covers 2024 Q1 → 2025 Q4 (8 quarters). Adjust as data
    expands.
    """
    out: list[str] = []
    year, q = start_year, 1
    for _ in range(n_quarters):
        out.append(f"{year}-Q{q}")
        q += 1
        if q > 4:
            q = 1
            year += 1
    return out


# --- Aggregation ------------------------------------------------------------


@dataclass
class WalkForwardAggregate:
    """Per-quarter metrics + aggregated scores."""

    candidate_id: str
    quarters: list[str] = field(default_factory=list)
    per_quarter: list[dict] = field(default_factory=list)
    mean_sharpe: float = 0.0
    mean_calmar: float = 0.0
    mean_trade_count: float = 0.0
    worst_quarter_sharpe: float = 0.0
    oos_quarter: Optional[str] = None
    oos_sharpe: Optional[float] = None
    oos_trade_count: int = 0
    oos_collapse: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def aggregate(per_quarter: list[tuple[str, dict]], oos_quarter: Optional[str] = None) -> WalkForwardAggregate:
    """Aggregate per-quarter metric blobs into walk-forward scores.

    ``per_quarter`` is a list of ``(quarter_label, metrics_blob)``. Each
    ``metrics_blob`` has the same shape as the v3 harness output. If
    ``oos_quarter`` is given we look it up separately to compute the
    OOS collapse flag.
    """
    if not per_quarter:
        return WalkForwardAggregate(candidate_id="?")

    quarters = [q for q, _ in per_quarter]
    sharpes = [m.get("sharpe") or 0.0 for _, m in per_quarter]
    calmars = [m.get("calmar") or 0.0 for _, m in per_quarter]
    counts = [m.get("trades_count", 0) for _, m in per_quarter]

    oos_metrics = None
    oos_sharpe = None
    oos_tc = 0
    oos_collapse = False
    if oos_quarter is not None:
        for q, m in per_quarter:
            if q == oos_quarter:
                oos_metrics = m
                break
        if oos_metrics is not None:
            oos_sharpe = oos_metrics.get("sharpe")
            oos_tc = oos_metrics.get("trades_count", 0)
            # Flag collapse if OOS sharpe < 0 or trade count < 15.
            oos_collapse = oos_sharpe is None or oos_sharpe < 0.0 or oos_tc < 15

    return WalkForwardAggregate(
        candidate_id=per_quarter[0][1].get("__candidate_id__", "?"),
        quarters=quarters,
        per_quarter=[{"quarter": q, **{k: v for k, v in m.items() if not k.startswith("_")}} for q, m in per_quarter],
        mean_sharpe=sum(sharpes) / len(sharpes),
        mean_calmar=sum(calmars) / len(calmars),
        mean_trade_count=sum(counts) / len(counts),
        worst_quarter_sharpe=min(sharpes),
        oos_quarter=oos_quarter,
        oos_sharpe=oos_sharpe,
        oos_trade_count=oos_tc,
        oos_collapse=oos_collapse,
    )


# --- Orchestration ----------------------------------------------------------


def walk_forward(
    *,
    candidate_id: str,
    tuning,  # TuningConstants or dict
    symbol_set: str,
    quarters: Iterable[str],
    state_root: Path,
    timeout_seconds: int = 900,
    anchor_step: int = 50,
) -> WalkForwardAggregate:
    """Run the v3 harness once per quarter and aggregate.

    This is a synchronous, single-process driver — it does NOT use the
    ProcessPool from M2 because quarter-level runs are serialised in
    practice (they share data and we don't want N×N concurrent loads).
    Operators wanting parallelism should call :func:`run_candidate`
    themselves.
    """
    per_quarter: list[tuple[str, dict]] = []
    quarters = list(quarters)
    last_quarter = quarters[-1] if quarters else None

    for q in quarters:
        run_dir = state.make_run_dir(state_root)
        r = run_candidate(
            candidate_id=f"{candidate_id}-{q}",
            tuning=tuning,
            symbol_set=symbol_set,
            quarter=q,
            run_dir=run_dir,
            anchor_step=anchor_step,
            timeout_seconds=timeout_seconds,
        )
        if r.decision == "error":
            # Skip errored quarters — they count as missing data.
            continue
        metrics = dict(r.metrics or {})
        metrics["__candidate_id__"] = candidate_id
        metrics["__quarter__"] = q
        per_quarter.append((q, metrics))

    return aggregate(per_quarter, oos_quarter=last_quarter)


# --- Persistence ------------------------------------------------------------


def save_walk_forward(agg: WalkForwardAggregate, path: Path) -> None:
    """Persist the aggregate to disk so the operator can inspect it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(agg.to_dict(), indent=2, default=str))


def load_walk_forward(path: Path) -> WalkForwardAggregate:
    """Reload a previously-saved aggregate."""
    return WalkForwardAggregate(**json.loads(Path(path).read_text()))
