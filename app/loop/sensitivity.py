"""Sensitivity scan — calibrate per-field σ per cluster.

For every tunable field we estimate the local gradient magnitude by
running ±σ perturbations against a fixed baseline. The result is a
:class:`SensitivityReport` that the search loop uses to scale σ up for
low-gradient fields (need more exploration) and down for high-gradient
fields (small step ⇒ small fitness change anyway).

The scan is intentionally synchronous — call it once before kicking off
the search loop, persist the report as ``loop_state/sensitivity.json``,
and reuse it across generations.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.config.tuning import TUNING, TuningConstants
from app.loop.mutation import (
    DEFAULT_CLUSTER_MAP,
    all_clusters,
    mutate_field,
)

# --- Report dataclasses ------------------------------------------------------


@dataclass
class FieldSensitivity:
    """One field's gradient estimate + recommended σ scale."""

    field: str
    cluster: str
    kind: str
    baseline_value: Any
    plus_delta: float  # fitness(baseline + σ) - fitness(baseline)
    minus_delta: float  # fitness(baseline - σ) - fitness(baseline)
    gradient_abs: float  # mean(|plus_delta|, |minus_delta|)
    recommended_sigma_scale: float  # 1.0 default; >1 means explore more


@dataclass
class SensitivityReport:
    """All field sensitivities + a default overall scale."""

    fields: list[FieldSensitivity] = field(default_factory=list)
    default_sigma_scale: float = 1.0

    def scale_for(self, field: str) -> float:
        """Return the recommended σ scale for ``field`` (default if not seen)."""
        for f in self.fields:
            if f.field == field:
                return f.recommended_sigma_scale
        return self.default_sigma_scale

    def to_dict(self) -> dict:
        return {
            "fields": [asdict(f) for f in self.fields],
            "default_sigma_scale": self.default_sigma_scale,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SensitivityReport:
        return cls(
            fields=[FieldSensitivity(**f) for f in d.get("fields", [])],
            default_sigma_scale=d.get("default_sigma_scale", 1.0),
        )


# --- Scanner -----------------------------------------------------------------


# A fitness function takes a TuningConstants and returns a float (higher = better).
FitnessFn = Callable[[TuningConstants], float]


def sensitivity_scan(
    *,
    baseline: Optional[TuningConstants] = None,
    fitness_fn: FitnessFn,
    sigma: float = 1.0,
    n_perturbations: int = 1,
    cluster_map: Optional[dict] = None,
    seed: Optional[int] = None,
    fields_to_skip: Iterable[str] = (),
) -> SensitivityReport:
    """Estimate per-field gradient magnitudes.

    For each tunable field, perturb it by ±σ (or ±σ·cur if kind ∈
    {rel_large, dict_per_key}) and measure the fitness delta. The
    ``recommended_sigma_scale`` is computed by:

        scale = clip(0.5 / (gradient + 1e-6), 0.25, 4.0)

    so a high-gradient field halves its σ and a low-gradient field can
    quadruple it (capped to avoid runaway).
    """
    rng = random.Random(seed)
    cm = cluster_map or DEFAULT_CLUSTER_MAP
    baseline = baseline or TUNING
    base_fitness = fitness_fn(baseline)

    out: list[FieldSensitivity] = []
    for cluster in all_clusters(cm):
        for name, kind, kwargs in cm[cluster]:
            if name in fields_to_skip:
                continue
            plus = mutate_field(name, kind, kwargs, baseline, rng, sigma_scale=sigma)
            minus = mutate_field(name, kind, kwargs, baseline, rng, sigma_scale=-sigma)
            plus_delta = fitness_fn(plus) - base_fitness
            minus_delta = fitness_fn(minus) - base_fitness
            grad_abs = (abs(plus_delta) + abs(minus_delta)) / 2.0

            # Scale rule: high gradient ⇒ scale down, low gradient ⇒ scale up.
            scale = 0.5 / (grad_abs + 1e-6)
            scale = max(0.25, min(4.0, scale))

            try:
                baseline_repr = float(getattr(baseline, name))
            except (TypeError, ValueError):
                # Dict / tuple / frozenset fields — store as str repr.
                baseline_repr = str(getattr(baseline, name))

            out.append(
                FieldSensitivity(
                    field=name,
                    cluster=cluster,
                    kind=kind,
                    baseline_value=baseline_repr,
                    plus_delta=float(plus_delta),
                    minus_delta=float(minus_delta),
                    gradient_abs=float(grad_abs),
                    recommended_sigma_scale=float(scale),
                )
            )

    return SensitivityReport(fields=out)


def save_report(report: SensitivityReport, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2))


def load_report(path: Path) -> SensitivityReport:
    return SensitivityReport.from_dict(json.loads(Path(path).read_text()))


# --- Mock fitness for unit tests --------------------------------------------


def mock_fitness_noisy(t: TuningConstants) -> float:
    """A noisy fitness that depends on a couple of real TuningConstants
    fields. Used in tests to drive the sensitivity scan without invoking
    the real backtest harness."""
    score = 0.0
    score += (t.a_grade_min - 70) * 0.01
    score += (t.target_atr_pct - 2.5) * 0.05
    score += (t.atr_window - 14) * -0.001
    # Inject tiny noise so the scan reports non-zero gradients.
    score += random.Random(t.a_grade_min).random() * 0.001
    return score
