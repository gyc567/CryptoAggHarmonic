"""Aggregator: combine Stage 1/3/4a/4b scores into signal/config/bench totals.

v3 changelog item 14 + docs/HarmonicSignal-Bench.md scoring.

Per-signal scoring (0-100):
  signal_score = (stage1/12 × 20) + (stage3/50 × 50) +
                 (stage4a/20 × 20) + (stage4b/10 × 10)

  weak_validity (stage1_score < 4) → × 0.5.

Per-config scoring:
  config_score = mean(signal_scores), with std surfaced separately for
  confidence intervals. Empty config → None.

Combined:
  bench_total = 0.6 × signal_score + 0.4 × config_score

Mutates the record with signal_score, config_score, bench_total.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, TypedDict

from bench.dataset.signal_record import SignalRecord


# Stage max values (per v3 spec).
MAX_STAGE1 = 12.0
MAX_STAGE3 = 50.0
MAX_STAGE4A = 20.0
MAX_STAGE4B = 10.0

# Signal-score sub-weights (sum = 100).
W_STAGE1 = 20.0
W_STAGE3 = 50.0
W_STAGE4A = 20.0
W_STAGE4B = 10.0

# Combined weights (signal vs config) — sum = 1.
W_SIGNAL = 0.6
W_CONFIG = 0.4

# weak_validity threshold and multiplier (per v3 changelog item 14).
WEAK_VALIDITY_THRESHOLD = 4
WEAK_VALIDITY_MULTIPLIER = 0.5


class AggregatorResult(TypedDict):
    signal_score: float
    config_score: Optional[float]
    bench_total: float
    weak_validity: bool
    n_signals: int


def signal_score(rec: SignalRecord) -> float:
    """Compute the per-signal score (0-100), mutate rec.signal_score, return it.

    If any stage score is None (e.g. stage2 didn't run), that component
    contributes 0. weak_validity flag → × 0.5 multiplier on the final.
    """
    s1 = (rec.stage1_score or 0.0) / MAX_STAGE1 * W_STAGE1
    s3 = (rec.stage3_score or 0.0) / MAX_STAGE3 * W_STAGE3
    s4a = (rec.stage4a_score or 0.0) / MAX_STAGE4A * W_STAGE4A
    s4b = (rec.stage4b_score or 0.0) / MAX_STAGE4B * W_STAGE4B
    raw = s1 + s3 + s4a + s4b
    if (rec.stage1_score is not None
            and rec.stage1_score < WEAK_VALIDITY_THRESHOLD):
        raw *= WEAK_VALIDITY_MULTIPLIER
        rec.weak_validity = True
    else:
        rec.weak_validity = False
    rec.signal_score = round(raw, 4)
    return rec.signal_score


def config_score(records: Iterable[SignalRecord]) -> Optional[float]:
    """Mean signal_score across records. None if no records have scores."""
    scores: List[float] = [
        r.signal_score for r in records if r.signal_score is not None
    ]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def bench_total(signal: float, config: Optional[float]) -> float:
    """Combine signal_score + config_score into a single total.

    If config is None (no aggregated data), fall back to signal-only.
    """
    if config is None:
        return round(signal, 4)
    return round(W_SIGNAL * signal + W_CONFIG * config, 4)


def aggregate(
    records: List[SignalRecord],
    config_id: Optional[str] = None,
) -> AggregatorResult:
    """Aggregate a list of records (same config) into one result.

    Mutates each record's signal_score. Sets config_score and bench_total
    on every record (they share the same value within a config).

    Args:
      records: list of SignalRecord from the same config_id.
      config_id: optional config identifier to stamp onto records'
        config_score field for downstream reporting.

    Returns:
      AggregatorResult dict.
    """
    if not records:
        return AggregatorResult(
            signal_score=0.0,
            config_score=None,
            bench_total=0.0,
            weak_validity=False,
            n_signals=0,
        )

    weak_count = 0
    for rec in records:
        signal_score(rec)
        if rec.weak_validity:
            weak_count += 1

    cfg = config_score(records)
    total = bench_total(records[0].signal_score or 0.0, cfg)
    for rec in records:
        rec.config_score = cfg
        rec.bench_total = total

    return AggregatorResult(
        signal_score=records[0].signal_score or 0.0,
        config_score=cfg,
        bench_total=total,
        weak_validity=weak_count > 0,
        n_signals=len(records),
    )
