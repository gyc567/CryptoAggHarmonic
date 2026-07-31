"""Bench-augmented Pareto point: compose bench metadata onto a ParetoPoint.

v3 changelog item 11: composition, not inheritance. We hold a
``ParetoPoint`` (the existing loop/pareto type) by reference and add
bench-specific fields for reporting. This keeps the bench framework
self-contained — touching ``app/loop/pareto.py`` would risk breaking
the live fitness loop.

The wrapper also exposes:
* ``win_rate`` and ``win_rate_ci`` for the bootstrap vs the live
  fitness signal — the leaderboard ranks Pareto fronts on a blend.
* ``bench_version`` / ``weights_version`` so a regenerated bench
  report can be diffed against an old one.
* ``low_confidence`` (computed in bench.scoring.confidence) so the
  loop can skip low-sample fronts without re-running scoring.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional, Tuple

from app.loop.pareto import ParetoPoint


BENCH_VERSION = "0.1.0"
"""Schema version of the bench report. Bump on incompatible changes."""

WEIGHTS_VERSION = "2026-07-31"
"""Date-stamped weights config. Bump when weights change in
bench.scoring.aggregator. Per v3 changelog item 16."""


@dataclass
class BenchAugmentedParetoPoint:
    """A ParetoPoint plus bench-specific metadata.

    Holds the live fitness point by reference (composition). Use
    ``to_dict()`` for serialisation.
    """

    base: ParetoPoint
    bench_version: str = BENCH_VERSION
    weights_version: str = WEIGHTS_VERSION
    signal_score: float = 0.0
    config_score: Optional[float] = None
    bench_total: float = 0.0
    low_confidence: bool = False
    n_signals: int = 0
    win_rate: float = 0.0
    win_rate_ci: Tuple[float, float] = (0.0, 1.0)
    exit_code: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise to a flat dict (base fields inlined under ``base_``)."""
        out = asdict(self)
        base = out.pop("base")
        prefixed = {f"base_{k}": v for k, v in base.items()}
        prefixed.update(out)
        return prefixed
