"""Stage 3: Outcome scoring (0-50).

v3 changelog + docs/HarmonicSignal-Bench.md Stage 3.

Sub-scores:
* result    (0-25): TP3=25, TP2=20, TP1=15, breakeven=8, stoploss=0
* rr        (0-10): net_rr thresholds (>=3:10, >=2:7, >=1:4, >=0.5:2)
* efficiency(0-10):  TP_achieve_bar / total_bars_held (TP only)
* stop_hit  (0 or -5): hit_stop_before_tp penalty (subtract 5)

Mutates ``rec.stage3_score``; returns the score.
"""

from __future__ import annotations

from bench.dataset.signal_record import SignalRecord, Outcome


def _result_subscore(outcome: Outcome) -> float:
    table = {
        "tp3": 25.0,
        "tp2": 20.0,
        "tp1": 15.0,
        "breakeven": 8.0,
        "stoploss": 0.0,
        "expired": 0.0,
        "incomplete": 0.0,
    }
    return table[outcome]


def _rr_subscore(net_rr: float | None) -> float:
    if net_rr is None:
        return 0.0
    if net_rr >= 3.0:
        return 10.0
    if net_rr >= 2.0:
        return 7.0
    if net_rr >= 1.0:
        return 4.0
    if net_rr >= 0.5:
        return 2.0
    return 0.0


def _efficiency_subscore(rec: SignalRecord) -> float:
    """0-10 from price_efficiency. price_efficiency=0 for non-TP exits."""
    pe = rec.price_efficiency
    if pe is None:
        return 0.0
    if pe >= 0.8:
        return 10.0
    if pe >= 0.5:
        return 6.0
    if pe >= 0.3:
        return 3.0
    # pe > 0 but < 0.3 (or 0): 1 point floor; pe == 0 exactly → 1 (loss
    # is not "efficient" but still completed)
    return 1.0


def _stop_hit_penalty(rec: SignalRecord) -> float:
    if rec.hit_stop_before_tp:
        return -5.0
    return 0.0


def stage3_score(rec: SignalRecord) -> float:
    """Compute Stage 3 score; mutate the record; return the score.

    Returns 0.0 (not raises) when ``outcome`` is None — the runner
    treats such records as DATA_INSUFFICIENT and may skip them
    before calling this function.
    """
    if rec.outcome is None:
        rec.stage3_score = 0.0
        return 0.0
    total = (
        _result_subscore(rec.outcome)
        + _rr_subscore(rec.net_rr)
        + _efficiency_subscore(rec)
        + _stop_hit_penalty(rec)
    )
    rec.stage3_score = round(total, 4)
    return rec.stage3_score
