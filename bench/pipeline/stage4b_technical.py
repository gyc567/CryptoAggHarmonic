"""Stage 4b: Technical scoring (0-10).

Re-uses the existing signal engine output fields on SignalRecord.

Sub-scores:
* grade          (0-4): A=4, B=2, C=0
* confluence     (0-3): >=3 → 3, >=2 → 2, >=1 → 1, else 0
* stability      (0-3): stable=3, mixed=1, unstable=0
"""

from __future__ import annotations

from bench.dataset.signal_record import Grade, SignalRecord


_GRADE_SCORE: dict[Grade, float] = {"A": 4.0, "B": 2.0, "C": 0.0}


def _grade_subscore(grade: Grade) -> float:
    return _GRADE_SCORE[grade]


def _confluence_subscore(confluence: float) -> float:
    if confluence >= 3:
        return 3.0
    if confluence >= 2:
        return 2.0
    if confluence >= 1:
        return 1.0
    return 0.0


def _stability_subscore(verdict: str) -> float:
    v = verdict.lower()
    if v == "stable":
        return 3.0
    if v == "mixed":
        return 1.0
    # unstable or unknown
    return 0.0


def stage4b_score(rec: SignalRecord) -> float:
    """Compute Stage 4b score; mutate the record; return the score."""
    total = (
        _grade_subscore(rec.grade)
        + _confluence_subscore(rec.confluence_score)
        + _stability_subscore(rec.stability_verdict)
    )
    rec.stage4b_score = round(total, 4)
    return rec.stage4b_score
