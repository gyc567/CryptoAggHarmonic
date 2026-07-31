"""Stage 1: Signal validity scoring (0-12, soft).

v3 changelog item 13-14 + docs/HarmonicSignal-Bench.md Stage 1 table.

Sub-scores:
* geometric (0-4): fib-ratio deviation, mapped from `prz_width_atr` proxy
* prz (0-2):     PRZ width in ATR units
* stop (0-2):    stop distance in ATR units
* data (0-2):    entry/stop/tp fields all present and direction-correct
* entry_zone (0-2): how reachable the PRZ is from current price

A record scoring < 4 is labelled ``weak_validity=True`` and enters
ConfigScore aggregation at 0.5× weight (v3 changelog item 14).

All inputs are taken from a SignalRecord; no external state. The
function mutates ``rec.stage1_score`` and ``rec.weak_validity`` and
returns the score.
"""

from __future__ import annotations

from typing import Tuple

from bench.dataset.signal_record import SignalRecord


def _geometric_subscore(rec: SignalRecord) -> float:
    """0-4 based on ``prz_width_atr`` as a proxy for fib deviation.

    Smaller PRZ widths score higher. A width of 0 → 4 points;
    a width of 1.0 ATR or larger → 0 points; linear between.
    """
    w = rec.prz_width_atr
    if w <= 0.0:
        return 4.0
    if w >= 1.0:
        return 0.0
    return round(4.0 * (1.0 - w), 4)


def _prz_subscore(rec: SignalRecord) -> float:
    """0-2 based on PRZ width in ATR (per v3 Stage 1 table)."""
    w = rec.prz_width_atr
    if w < 0.5:
        return 2.0
    if w < 1.0:
        return 1.0
    return 0.0


def _stop_subscore(rec: SignalRecord) -> float:
    """0-2 based on stop distance in ATR units (per v3 Stage 1 table).

    Optimal range [0.5, 3.0] ATR; linear decay outside.
    """
    if rec.atr_at_entry <= 0.0:
        return 0.0
    stop_distance = abs(rec.entry_price - rec.stop_price)
    sd_atr = stop_distance / rec.atr_at_entry
    if 0.5 <= sd_atr <= 3.0:
        return 2.0
    if sd_atr < 0.5:
        # Linear decay from 2.0 (at 0.5) to 0.0 (at 0.0)
        return round(2.0 * (sd_atr / 0.5), 4)
    # sd_atr > 3.0: decay from 2.0 (at 3.0) to 0.0 (at 6.0)
    return round(max(0.0, 2.0 * (1.0 - (sd_atr - 3.0) / 3.0)), 4)


def _data_subscore(rec: SignalRecord) -> float:
    """0-2 if entry/stop/tp present and direction-correct.

    Long: stop < entry < tp1. Short: stop > entry > tp1.
    """
    if rec.entry_price <= 0 or rec.stop_price <= 0 or rec.tp1 <= 0:
        return 0.0
    if rec.direction == "long":
        return 2.0 if rec.stop_price < rec.entry_price < rec.tp1 else 0.0
    # short — type system constrains direction to Literal["long","short"]
    return 2.0 if rec.stop_price > rec.entry_price > rec.tp1 else 0.0


def _entry_zone_subscore(rec: SignalRecord) -> float:
    """0-2 (v3 new) — entry-zone reachability from current price.

    entry_offset_atr > 0  → price already past PRZ, hard to enter.
    entry_offset_atr < 0  → price not yet at PRZ, can wait.

    Mapping (v3 changelog item 13):
        [-0.5, +0.5]            → 2 (in range)
        [+0.5, +1.5]            → linear 2 → 1
        > +1.5                  → 0 (untradeable)
        < -0.5                  → 2 (no penalty for "not yet")
    """
    off = rec.entry_offset_atr
    if off > 1.5:
        return 0.0
    if off <= 0.5:
        return 2.0
    # (0.5, 1.5]: linear 2 → 1
    return round(2.0 - (off - 0.5), 4)


def stage1_score(rec: SignalRecord) -> Tuple[float, bool]:
    """Compute Stage 1 score; mutate the record and return (score, weak).

    Per v3 changelog item 14: ``weak_validity`` is set when total < 4.
    The label is a soft report-level signal — does NOT exclude the
    signal from scoring. Aggregation weighting is the aggregator's
    job (see bench/scoring/aggregator.py).
    """
    geometric = _geometric_subscore(rec)
    prz = _prz_subscore(rec)
    stop = _stop_subscore(rec)
    data = _data_subscore(rec)
    entry_zone = _entry_zone_subscore(rec)
    total = geometric + prz + stop + data + entry_zone
    weak = total < 4.0
    rec.stage1_score = round(total, 4)
    rec.weak_validity = weak
    return rec.stage1_score, weak
