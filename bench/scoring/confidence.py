"""Confidence: Wilson CI for binomial proportions + Benjamini-Hochberg FDR.

v3 changelog item 13 + docs/HarmonicSignal-Bench.md confidence.

* ``wilson_ci(successes, n, alpha)`` — Wilson score interval for the
  observed win rate. Returns ``(lower, upper)`` at confidence level
  ``1 - alpha``. Degrades to ``(0, 1)`` if ``n == 0``.

* ``bh_fdr(pvalues, alpha)`` — Benjamini-Hochberg step-up procedure.
  Returns ``adjusted_pvalues`` (same length, original order) and
  ``reject_mask`` (bool array, ``True`` ⇒ statistically significant at
  the configured FDR level).

The Wilson interval is preferred over the normal approximation because
it stays in [0, 1] for small samples and asymmetric counts (e.g. 0/N).
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple


def wilson_ci(
    successes: int,
    n: int,
    alpha: float = 0.05,
) -> Tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Args:
      successes: count of positive outcomes.
      n: total trials.
      alpha: significance level (default 0.05 → 95% CI).

    Returns:
      (lower, upper) bounds, both clamped to [0, 1].
    """
    if n <= 0:
        return 0.0, 1.0
    if successes < 0 or successes > n:
        raise ValueError(
            f"successes={successes} must satisfy 0 ≤ successes ≤ n={n}"
        )
    if not 0 < alpha < 1:
        raise ValueError(f"alpha={alpha} must be in (0, 1)")

    z = _z_for_alpha(alpha)
    p_hat = successes / n
    denom = 1.0 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denom
    spread = (
        z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n)) / denom
    )
    lower = max(0.0, center - spread)
    upper = min(1.0, center + spread)
    return lower, upper


def _z_for_alpha(alpha: float) -> float:
    """Return the two-tailed z value for the given alpha.

    Supports the standard cases (0.10 → 1.6449, 0.05 → 1.9600,
    0.01 → 2.5758, 0.001 → 3.2905). For anything else, raises.
    """
    table = {
        0.10: 1.6449,
        0.05: 1.9600,
        0.01: 2.5758,
        0.001: 3.2905,
    }
    z = table.get(round(alpha, 4))
    if z is None:
        raise ValueError(
            f"alpha={alpha} not in lookup table {sorted(table)}; "
            "use 0.10 / 0.05 / 0.01 / 0.001"
        )
    return z


def bh_fdr(
    pvalues: Sequence[float],
    alpha: float = 0.05,
) -> Tuple[List[float], List[bool]]:
    """Benjamini-Hochberg step-up FDR adjustment.

    Args:
      pvalues: list of raw p-values (one per hypothesis).
      alpha: target false discovery rate.

    Returns:
      (adjusted_pvalues, reject_mask) — same length as input, same
      order. ``reject_mask[i]`` is True iff hypothesis i is rejected
      (i.e. its adjusted p-value ≤ alpha).
    """
    n = len(pvalues)
    if n == 0:
        return [], []
    if not 0 < alpha < 1:
        raise ValueError(f"alpha={alpha} must be in (0, 1)")
    for p in pvalues:
        if p < 0 or p > 1:
            raise ValueError(f"p-value {p} outside [0, 1]")

    # Sort indices by ascending p-value.
    order = sorted(range(n), key=lambda i: pvalues[i])
    sorted_p = [pvalues[i] for i in order]

    # adjusted = min over j >= i of (sorted_p[j] * n / (j + 1))
    # Work from the largest p-value down to enforce monotonicity.
    raw_adjusted: List[float] = [0.0] * n
    running_min = 1.0
    for rank in range(n, 0, -1):
        idx = rank - 1
        bh_step = sorted_p[idx] * n / rank
        running_min = min(running_min, bh_step)
        raw_adjusted[idx] = min(running_min, 1.0)

    # Map back to original order.
    adjusted = [0.0] * n
    for rank, original_idx in enumerate(order):
        adjusted[original_idx] = raw_adjusted[rank]

    reject = [p <= alpha for p in adjusted]
    return adjusted, reject


def low_confidence(
    records: Sequence,
    *,
    min_n: int = 30,
    min_lower: float = 0.4,
    max_upper: float = 0.6,
) -> bool:
    """Return True if the config is too uncertain to publish.

    A config is "low confidence" if any of:
    * fewer than ``min_n`` signals,
    * the Wilson lower bound on win rate < ``min_lower``,
    * the Wilson upper bound on win rate < ``max_upper`` (i.e. the
      95% CI is entirely below the breakeven threshold).

    The sequence must have ``outcome`` and ``config_score`` (or
    whatever attribute the caller wants to test win rate on) — we
    default to counting ``outcome in ('tp1','tp2','tp3')``.
    """
    n = len(records)
    if n < min_n:
        return True
    wins = sum(1 for r in records if getattr(r, "outcome", None) in ("tp1", "tp2", "tp3"))
    lower, upper = wilson_ci(wins, n)
    if lower < min_lower:
        return True
    if upper < max_upper:
        return True
    return False
