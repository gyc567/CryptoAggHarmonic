"""Aggregator: combine Stage 1/3/4a/4b scores into signal/config/bench totals.

v3 changelog item 14 + docs/HarmonicSignal-Bench.md Level 1/2/3.

Level 1 (per-signal, 0-100):
  signal_score = (stage1/12 × 20) + (stage3/50 × 50) +
                 (stage4a/20 × 20) + (stage4b/10 × 10)
  weak_validity (stage1_score < 4) → × 0.5 multiplier.

Level 2 (per-config, 0-100) — per-pattern aggregation:
  For each pattern_family:
    pattern_score = (
        pattern_avg_score × 0.40 +
        pattern_win_rate × 100 × 0.25 +
        min(pattern_avg_rr / 5, 1) × 100 × 0.20 +
        min(pattern_signal_count / 100, 1) × 100 × 0.15
    )
  ConfigScore = Σ(pattern_score_i × n_i) / Σ(n_i)
  Penalty: if any pattern has n < 10, multiply by 0.9 (low_confidence).

Level 3 (bench_total):
  bench_total = 0.6 × signal_score + 0.4 × config_score
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, TypedDict

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

# Per-pattern weights (per v3 spec Level 2 step A) — sum = 1.
W_PATTERN_AVG_SCORE = 0.40
W_PATTERN_WIN_RATE = 0.25
W_PATTERN_AVG_RR = 0.20
W_PATTERN_SAMPLE_BONUS = 0.15

# Per-pattern reference values (per v3 spec).
RR_REFERENCE = 5.0      # cap for avg_rr contribution
SAMPLE_REFERENCE = 100  # cap for sample-count contribution
MIN_SAMPLES_PER_PATTERN = 10  # below this → low_confidence penalty
LOW_SAMPLE_PENALTY = 0.9


class PatternScore(TypedDict):
    pattern_family: str
    signal_count: int
    win_rate: float
    avg_signal_score: float
    avg_rr_winning: float
    pattern_score: float


class AggregatorResult(TypedDict):
    signal_score: float
    config_score: Optional[float]
    bench_total: float
    weak_validity: bool
    low_confidence: bool
    n_signals: int
    n_patterns: int
    pattern_scores: List[PatternScore]


# ---------- Level 1: per-signal ----------

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


# ---------- Level 2: per-config (per-pattern) ----------

def _group_by_pattern(
    records: Iterable[SignalRecord],
) -> Dict[str, List[SignalRecord]]:
    groups: Dict[str, List[SignalRecord]] = defaultdict(list)
    for r in records:
        family = r.pattern_family or ""
        groups[family].append(r)
    return groups


def _pattern_stats(pattern_family: str, recs: List[SignalRecord]) -> PatternScore:
    """Compute per-pattern Level 2 inputs and the pattern_score itself."""
    n = len(recs)
    wins = [r for r in recs if r.outcome in ("tp1", "tp2", "tp3")]
    losses = [r for r in recs if r.outcome == "stoploss"]
    decided = len(wins) + len(losses)
    win_rate = len(wins) / decided if decided > 0 else 0.0
    scores = [r.signal_score for r in recs if r.signal_score is not None]
    avg_score = sum(scores) / len(scores) if scores else 0.0
    winning_rrs = [r.net_rr for r in wins if r.net_rr is not None]
    avg_rr_win = sum(winning_rrs) / len(winning_rrs) if winning_rrs else 0.0
    pattern_score = (
        avg_score * W_PATTERN_AVG_SCORE
        + win_rate * 100 * W_PATTERN_WIN_RATE
        + min(avg_rr_win / RR_REFERENCE, 1.0) * 100 * W_PATTERN_AVG_RR
        + min(n / SAMPLE_REFERENCE, 1.0) * 100 * W_PATTERN_SAMPLE_BONUS
    )
    return PatternScore(
        pattern_family=pattern_family,
        signal_count=n,
        win_rate=round(win_rate, 4),
        avg_signal_score=round(avg_score, 4),
        avg_rr_winning=round(avg_rr_win, 4),
        pattern_score=round(pattern_score, 4),
    )


def config_score(records: Iterable[SignalRecord]) -> Optional[float]:
    """Weighted-mean of per-pattern scores. None if no records.

    Returns ``config_score`` rounded to 4 decimals. Also returns the
    low_confidence flag via ``config_score_with_patterns`` if the
    caller wants the pattern breakdown.
    """
    result = config_score_with_patterns(records)
    return result[0]


def config_score_with_patterns(
    records: Iterable[SignalRecord],
) -> tuple[Optional[float], bool, List[PatternScore]]:
    """Like ``config_score`` but returns ``(score, low_confidence, per_pattern)``.

    low_confidence is True if any pattern has fewer than
    ``MIN_SAMPLES_PER_PATTERN`` signals.
    """
    recs = list(records)
    if not recs:
        return None, False, []
    groups = _group_by_pattern(recs)
    pattern_scores = [
        _pattern_stats(fam, group) for fam, group in sorted(groups.items())
    ]
    total_n = sum(p["signal_count"] for p in pattern_scores)
    weighted = sum(
        p["pattern_score"] * p["signal_count"] for p in pattern_scores
    ) / total_n
    low_conf = any(
        p["signal_count"] < MIN_SAMPLES_PER_PATTERN for p in pattern_scores
    )
    if low_conf:
        weighted *= LOW_SAMPLE_PENALTY
    return round(weighted, 4), low_conf, pattern_scores


# ---------- Level 3: combined ----------

def bench_total(signal: float, config: Optional[float]) -> float:
    """Combine signal_score + config_score into a single total.

    If config is None (no aggregated data), fall back to signal-only.
    """
    if config is None:
        return round(signal, 4)
    return round(W_SIGNAL * signal + W_CONFIG * config, 4)


# ---------- Orchestrator ----------

def aggregate(
    records: List[SignalRecord],
    config_id: Optional[str] = None,
) -> AggregatorResult:
    """Aggregate a list of records (same config) into one result.

    Mutates each record's signal_score, config_score, bench_total, and
    weak_validity. Returns a summary dict with per-pattern breakdown.
    """
    if not records:
        return AggregatorResult(
            signal_score=0.0,
            config_score=None,
            bench_total=0.0,
            weak_validity=False,
            low_confidence=False,
            n_signals=0,
            n_patterns=0,
            pattern_scores=[],
        )

    weak_count = 0
    for rec in records:
        signal_score(rec)
        if rec.weak_validity:
            weak_count += 1

    cfg, low_conf, pattern_scores = config_score_with_patterns(records)
    total = bench_total(records[0].signal_score or 0.0, cfg)
    for rec in records:
        rec.config_score = cfg
        rec.bench_total = total

    return AggregatorResult(
        signal_score=records[0].signal_score or 0.0,
        config_score=cfg,
        bench_total=total,
        weak_validity=weak_count > 0,
        low_confidence=low_conf,
        n_signals=len(records),
        n_patterns=len(pattern_scores),
        pattern_scores=pattern_scores,
    )
