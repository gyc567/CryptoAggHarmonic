"""Discipline filters for forming harmonic candidates.

Three live-trading checks the upstream ``HarmonicSearch`` does NOT enforce:

* **Path integrity** — between the C pivot and the latest bar, did price
  already traverse the PRZ? If yes, the pattern is structurally finished
  (or dead) and should not be re-entered. (Audit Q3: this is the corrected
  check — the reference used ``low < stop`` which conflates two different
  states.)
* **TTL** — ``bars_since_c > max_ttl`` means the C point is too old; the
  pattern may have been invalidated by intervening structure. Marked
  ``stale=True`` (downgrade) instead of dropped, so the dashboard can still
  show it as a "reference zone".
* **TP2 boundary** — if price already crossed the second take-profit level,
  the trade played out without us; the candidate is dead.

All three checks are pure: no I/O, no logging. The orchestrator loops them
per candidate.

Three-layer defense (L1 type-check → L2 contracts → L3 schema) lives one level
up; this module is **L2-bound** — every public function carries ``@require``
preconditions so invalid inputs fail fast with a ``ViolationError`` instead
of silently producing wrong ``DisciplineResult``s that downstream graders
trust.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from icontract import require

from app.config.tuning import TUNING
from app.domain.forming_schemas import CandidateMetrics
from app.domain.signals import Candidate, compute_targets


# --- Default TTL --------------------------------------------------------------
#
# Reference default is 40 bars on 4H (~6.7 days). The signal engine also runs
# its own staleness check (``MAX_D_AGE_BARS``) anchored at the D point;
# this module's TTL is anchored at the C point and only applies to forming
# patterns (D not yet confirmed). Callers may override per-request.
# Backwards-compat alias — the value lives in TUNING.default_ttl_bars.

DEFAULT_TTL_BARS = TUNING.default_ttl_bars


@dataclass(frozen=True)
class DisciplineResult:
    """Outcome of running all three discipline checks on one candidate.

    ``passed`` is the master switch: ``False`` means the candidate should be
    excluded from the executable list. ``metrics`` carries the per-check
    booleans so the frontend can show why a row was marked stale / breached /
    past_tp2.
    """

    passed: bool
    metrics: CandidateMetrics


def _bars_since(c_idx: Optional[int], total_bars: int) -> int:
    """How many bars have closed since ``c_idx``. Clamps negatives to 0."""
    if c_idx is None or c_idx < 0:
        return 0
    return max(0, total_bars - 1 - c_idx)


def _prz_was_touched(
    after: pd.DataFrame, prz_low: float, prz_high: float, bullish: bool
) -> bool:
    """True iff price pierced the PRZ band on any bar after the C pivot.

    For a long candidate, "touched" means the bar's ``low`` is at or below the
    PRZ upper bound AND the bar's ``high`` is at or above the PRZ lower bound
    (i.e. any part of the bar visited the zone). We deliberately use the
    full bar range rather than ``close`` because a wick-through counts as
    a touch — and a wick that touched but didn't close-through is exactly
    the "unfinished" state we want to flag for forming patterns.

    For a short candidate the mirror holds.

    Special case: if the bar is wholly above the PRZ (bullish, ``low > prz_high``)
    or wholly below (bearish, ``high < prz_low``) then price has NOT touched
    the zone yet — return False.
    """
    if after.empty:
        return False
    if bullish:
        # bar touched PRZ iff high >= prz_low (wicked into zone from above)
        # AND low <= prz_high (didn't overshoot completely below the zone).
        touched = (after["high"] >= prz_low) & (after["low"] <= prz_high)
        return bool(touched.any())
    # bearish
    touched = (after["low"] <= prz_high) & (after["high"] >= prz_low)
    return bool(touched.any())


def _past_tp2(
    current_price: float, candidate: Candidate, bullish: bool
) -> bool:
    """True iff current price has already crossed the second take-profit."""
    prz_mid = (candidate.prz_low + candidate.prz_high) / 2
    if prz_mid <= 0:
        return False
    tp2_price = compute_targets(candidate, prz_mid)[1].price
    if bullish:
        return current_price > tp2_price
    return current_price < tp2_price


def evaluate(
    df: pd.DataFrame,
    candidate: Candidate,
    current_price: float,
    max_ttl: int = DEFAULT_TTL_BARS,
    c_idx: Optional[int] = None,
) -> DisciplineResult:
    """Run path-integrity / TTL / TP2 checks against one candidate.

    Args:
        df: Full candle DataFrame (must contain ``high``/``low`` columns).
        candidate: The harmonic candidate from upstream.
        current_price: Latest close; used for the TP2 cross check.
        max_ttl: TTL in bars. ``bars_since_c > max_ttl`` ⇒ stale.
        c_idx: Index of the C point in ``df``. If ``None`` we try to recover
            it from ``candidate.times[-2]`` (one-before-last; for XABCD the
            last entry is D). Falls back to 0 if neither is available.

    Returns:
        A :class:`DisciplineResult` whose ``passed`` flag is the master
        switch; ``metrics`` always carries the per-check outcomes so the
        frontend can render diagnostics.
    """
    @require(lambda df: len(df) > 0, "df must not be empty")
    @require(lambda candidate: candidate.prz_low > 0 and candidate.prz_high > 0,
             "candidate PRZ bounds must be positive")
    @require(lambda current_price: current_price > 0,
             "current_price must be positive")
    @require(lambda max_ttl: max_ttl >= 0, "max_ttl must be non-negative")
    def _check_inputs(**_kwargs) -> None:
        return None

    _check_inputs(df=df, candidate=candidate, current_price=current_price,
                  max_ttl=max_ttl)

    n = len(df)
    if c_idx is None:
        # Prefer the new ``indices`` field (bar positions in the source df).
        # Fall back to ``times[-2]`` for legacy candidates that pre-date the
        # indices split. ``times[-2]`` may still be epoch seconds for newer
        # candidates so this fallback is no longer reliable.
        if getattr(candidate, "indices", None) and len(candidate.indices) >= 2:
            c_idx = int(candidate.indices[-2])
        elif candidate.times and len(candidate.times) >= 2:
            c_idx = int(candidate.times[-2])
        else:
            c_idx = 0

    bars_since_c = _bars_since(c_idx, n)
    bullish = candidate.bullish

    # Gate 1: path integrity. The slice after C is what determines whether
    # the PRZ was ever touched (= pattern finished or dead).
    after = df.iloc[c_idx + 1:] if c_idx + 1 < n else df.iloc[0:0]
    breached = _prz_was_touched(after, candidate.prz_low, candidate.prz_high, bullish)

    # Gate 2: TTL.
    stale = bars_since_c > max_ttl

    # Gate 3: TP2 cross.
    past_tp2 = _past_tp2(current_price, candidate, bullish)

    metrics = CandidateMetrics(
        bars_since_c=bars_since_c,
        stale=stale,
        breached_stop=breached,
        past_tp2=past_tp2,
        in_prz=candidate.prz_low <= current_price <= candidate.prz_high,
        dist_pct=_dist_pct(current_price, candidate, bullish),
    )

    # Master rule:
    #   breached_stop=True  → pattern is finished or dead, drop
    #   past_tp2=True       → trade already played out, drop
    #   stale=True          → downgrade only, keep visible
    passed = not breached and not past_tp2
    return DisciplineResult(passed=passed, metrics=metrics)


def _dist_pct(
    current_price: float, candidate: Candidate, bullish: bool
) -> float:
    """% distance from current price to the nearest PRZ edge.

    Always non-negative. ``0.0`` when price is inside the PRZ.
    """
    lo, hi = candidate.prz_low, candidate.prz_high
    if current_price <= 0 or lo <= 0 or hi <= 0:
        return 0.0
    if lo <= current_price <= hi:
        return 0.0
    if bullish:
        # PRZ is below price → distance to PRZ top
        if current_price > hi:
            return (current_price / hi - 1) * 100
        # Price has overshot below PRZ (rare for forming) → distance to lo
        return (lo / current_price - 1) * 100
    # bearish
    if current_price < lo:
        return (lo / current_price - 1) * 100
    return (current_price / hi - 1) * 100