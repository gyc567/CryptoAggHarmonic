"""Regime-bucket aggregation.

Plan §3.5 calls for "regime-bucket decomposition" — every metric blob
carries a ``by_regime`` dict (from the v3 harness). This module:

* takes a list of ``by_regime`` dicts (one per quarter / per walk-forward
  step) and aggregates per-regime totals
* computes the worst-regime Sharpe across the union of regimes
* flags candidates that are heavily regime-skewed (most trades in one
  regime, near-zero in others)

The output is a flat dict so the v3 harness can read it back via
``metrics["regime_aggregate"]``.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Iterable


@dataclass
class RegimeAggregate:
    """Per-regime aggregated stats across N runs / quarters."""

    regimes: dict[str, dict] = field(default_factory=dict)
    worst_regime_sharpe: float = 0.0
    worst_regime_label: str = "unknown"
    dispersion: float = 0.0  # stddev of per-regime sharpes
    skewed: bool = False  # True if one regime has ≥85% of trades

    def to_dict(self) -> dict:
        return asdict(self)


def aggregate_regimes(by_regime_blobs: Iterable[dict],
                      skew_threshold: float = 0.85) -> RegimeAggregate:
    """Combine multiple ``by_regime`` dicts into one aggregate.

    Each input dict maps regime name → ``{n, sharpe, total_r, ...}``.
    We sum the trade counts, weighted-average the sharpes, and track the
    worst observed sharpe per regime.

    Regimes with ``n < 3`` in any single run are dropped from the
    per-regime mean (insufficient sample) but their trades still count
    toward the global skew calculation.
    """
    n_total = 0
    counts: dict[str, int] = defaultdict(int)
    sharpe_sums: dict[str, float] = defaultdict(float)
    sharpe_n: dict[str, int] = defaultdict(int)

    for blob in by_regime_blobs:
        for regime, stats in (blob or {}).items():
            n = int(stats.get("n", 0))
            counts[regime] += n
            n_total += n
            s = stats.get("sharpe")
            if s is None or n < 3:
                continue
            sharpe_sums[regime] += float(s)
            sharpe_n[regime] += 1

    regimes: dict[str, dict] = {}
    for regime in sorted(counts):
        n = counts[regime]
        sharpe_mean = (
            sharpe_sums[regime] / sharpe_n[regime] if sharpe_n[regime] else None
        )
        regimes[regime] = {
            "n": n,
            "share": (n / n_total) if n_total else 0.0,
            "sharpe_mean": sharpe_mean,
        }

    # Worst regime = min sharpe_mean over regimes with at least one sample.
    mean_sharpes = [
        (r, v["sharpe_mean"]) for r, v in regimes.items()
        if v["sharpe_mean"] is not None
    ]
    if mean_sharpes:
        worst_label, worst_sharpe = min(mean_sharpes, key=lambda kv: kv[1])
        dispersion = _stddev([s for _, s in mean_sharpes])
    else:
        worst_label, worst_sharpe = "unknown", 0.0
        dispersion = 0.0

    # Skew detection — one regime holds ≥ skew_threshold of trades.
    skewed = False
    if n_total > 0 and regimes:
        dominant_share = max(r["share"] for r in regimes.values())
        skewed = dominant_share >= skew_threshold

    return RegimeAggregate(
        regimes=regimes,
        worst_regime_sharpe=float(worst_sharpe),
        worst_regime_label=worst_label,
        dispersion=float(dispersion),
        skewed=skewed,
    )


def _stddev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
    return var ** 0.5