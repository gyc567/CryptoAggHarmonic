"""Tests for bench.scoring.aggregator."""

from __future__ import annotations

import pytest

from bench.dataset.signal_record import empty_record
from bench.scoring.aggregator import (
    MAX_STAGE1,
    MAX_STAGE3,
    MAX_STAGE4A,
    MAX_STAGE4B,
    WEAK_VALIDITY_MULTIPLIER,
    WEAK_VALIDITY_THRESHOLD,
    aggregate,
    bench_total,
    config_score,
    signal_score,
)


def _rec(
    *,
    s1: float | None = 12.0,
    s3: float | None = 50.0,
    s4a: float | None = 20.0,
    s4b: float | None = 10.0,
):
    return empty_record(
        stage1_score=s1,
        stage3_score=s3,
        stage4a_score=s4a,
        stage4b_score=s4b,
    )


# ---------- signal_score ----------

def test_signal_score_perfect_is_100() -> None:
    rec = _rec()
    assert signal_score(rec) == 100.0
    assert rec.signal_score == 100.0
    assert rec.weak_validity is False


def test_signal_score_zero_is_zero() -> None:
    rec = _rec(s1=0, s3=0, s4a=0, s4b=0)
    assert signal_score(rec) == 0.0


def test_signal_score_half_each() -> None:
    rec = _rec(s1=MAX_STAGE1 / 2, s3=MAX_STAGE3 / 2, s4a=MAX_STAGE4A / 2, s4b=MAX_STAGE4B / 2)
    assert signal_score(rec) == pytest.approx(50.0)


def test_signal_score_weak_validity_halves() -> None:
    # Set all stages max except stage1, then trigger weak_validity by
    # setting stage1 < threshold. Verify the 0.5× applies.
    rec_max = _rec()  # 100
    rec_weak = _rec(s1=WEAK_VALIDITY_THRESHOLD - 1)  # stage1=3 → weak
    # rec_max: s1=12 → 20, s3=50 → 50, s4a=20 → 20, s4b=10 → 10. Total=100.
    # rec_weak: s1=3 → 5, s3=50 → 50, s4a=20 → 20, s4b=10 → 10. Raw=85, weak → 42.5.
    assert signal_score(rec_max) == pytest.approx(100.0)
    assert signal_score(rec_weak) == pytest.approx(42.5)
    assert rec_weak.weak_validity is True


def test_signal_score_weak_validity_at_threshold_no_halving() -> None:
    # stage1 == threshold → no halving
    rec = _rec(s1=WEAK_VALIDITY_THRESHOLD)  # s1=4
    # s1=4 → (4/12)*20 = 6.667, s3=50, s4a=20, s4b=10. Total = 86.667.
    # NOT weak (threshold check is strict <).
    assert signal_score(rec) == pytest.approx(86.6667, abs=0.01)
    assert rec.weak_validity is False


def test_signal_score_missing_stage_contributes_zero() -> None:
    rec = _rec(s3=None, s4a=None, s4b=None)  # only stage1
    # s1 = 12 → W_STAGE1 = 20
    assert signal_score(rec) == pytest.approx(20.0)


def test_signal_score_all_missing_returns_zero() -> None:
    rec = _rec(s1=None, s3=None, s4a=None, s4b=None)
    assert signal_score(rec) == 0.0


def test_signal_score_mutates_rec() -> None:
    rec = _rec()
    signal_score(rec)
    assert rec.signal_score is not None
    assert rec.weak_validity is False


def test_signal_score_weak_validity_multiplier_constant() -> None:
    assert WEAK_VALIDITY_MULTIPLIER == 0.5


# ---------- config_score ----------

def test_config_score_mean() -> None:
    r1 = _rec()
    r2 = _rec(s3=0, s4a=0, s4b=0)  # 20 (only stage1)
    signal_score(r1)
    signal_score(r2)
    assert config_score([r1, r2]) == pytest.approx(60.0)


def test_config_score_empty_returns_none() -> None:
    assert config_score([]) is None


def test_config_score_no_scores_returns_none() -> None:
    r = empty_record()  # all scores None
    assert config_score([r]) is None


def test_config_score_single_record() -> None:
    r = _rec()
    signal_score(r)
    assert config_score([r]) == 100.0


# ---------- bench_total ----------

def test_bench_total_combines() -> None:
    # 0.6 × 100 + 0.4 × 50 = 60 + 20 = 80
    assert bench_total(100.0, 50.0) == pytest.approx(80.0)


def test_bench_total_no_config_falls_back() -> None:
    assert bench_total(70.0, None) == 70.0


def test_bench_total_rounded() -> None:
    # 0.6 × 33 + 0.4 × 25 = 19.8 + 10.0 = 29.8
    out = bench_total(33.0, 25.0)
    assert out == pytest.approx(29.8)


# ---------- aggregate ----------

def test_aggregate_empty_returns_zero() -> None:
    result = aggregate([])
    assert result == {
        "signal_score": 0.0,
        "config_score": None,
        "bench_total": 0.0,
        "weak_validity": False,
        "n_signals": 0,
    }


def test_aggregate_single_record() -> None:
    rec = _rec()
    result = aggregate([rec])
    assert result["n_signals"] == 1
    assert result["signal_score"] == 100.0
    assert result["config_score"] == 100.0
    assert result["bench_total"] == pytest.approx(100.0)
    assert result["weak_validity"] is False
    # record also gets config_score and bench_total written
    assert rec.config_score == 100.0
    assert rec.bench_total == pytest.approx(100.0)


def test_aggregate_multiple_records_averages_config() -> None:
    r1 = _rec()                                       # 100
    r2 = _rec(s3=0, s4a=0, s4b=0)                     # 20
    # Avoid stage1=0 here — that triggers weak_validity and halves the score.
    r3 = _rec(s1=MAX_STAGE1 / 2, s3=0, s4a=0)         # 10 + 0 + 0 + 10 = 20
    result = aggregate([r1, r2, r3])
    assert result["config_score"] == pytest.approx((100 + 20 + 20) / 3)
    assert result["n_signals"] == 3
    # bench_total uses first record's signal_score = 100, combined with config mean
    assert result["bench_total"] == pytest.approx(0.6 * 100 + 0.4 * ((100 + 20 + 20) / 3))


def test_aggregate_marks_weak_validity_if_any_record_is_weak() -> None:
    r1 = _rec()  # strong
    r2 = _rec(s1=2)  # weak
    result = aggregate([r1, r2])
    assert result["weak_validity"] is True


def test_aggregate_writes_config_score_to_all_records() -> None:
    r1 = _rec()
    r2 = _rec(s3=0, s4a=0, s4b=0)
    aggregate([r1, r2])
    assert r1.config_score == r2.config_score


def test_aggregate_writes_bench_total_to_all_records() -> None:
    r1 = _rec()
    r2 = _rec(s3=0)
    aggregate([r1, r2])
    assert r1.bench_total == r2.bench_total


def test_aggregate_idempotent() -> None:
    """Running aggregate twice yields the same config_score."""
    r1, r2 = _rec(), _rec(s3=0)
    aggregate([r1, r2])
    cfg1 = r1.config_score
    aggregate([r1, r2])  # second run
    assert r1.config_score == cfg1


def test_aggregate_with_none_scores_skipped() -> None:
    """Records with all-None scores are ignored when computing config_score."""
    strong = _rec()
    blank = empty_record()  # all stage scores None
    result = aggregate([strong, blank])
    # blank's signal_score becomes 0, so config_score = (100 + 0) / 2 = 50
    assert result["config_score"] == pytest.approx(50.0)
    assert result["n_signals"] == 2
