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
    config_score_with_patterns,
    signal_score,
)


def _rec(
    *,
    s1: float | None = 12.0,
    s3: float | None = 50.0,
    s4a: float | None = 20.0,
    s4b: float | None = 10.0,
    pattern_family: str | None = "XABCD",
    outcome: str | None = "tp2",
    net_rr: float | None = 2.0,
):
    return empty_record(
        stage1_score=s1,
        stage3_score=s3,
        stage4a_score=s4a,
        stage4b_score=s4b,
        pattern_family=pattern_family or "XABCD",
        outcome=outcome,
        net_rr=net_rr,
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
    rec_max = _rec()  # 100
    rec_weak = _rec(s1=WEAK_VALIDITY_THRESHOLD - 1)
    assert signal_score(rec_max) == pytest.approx(100.0)
    assert signal_score(rec_weak) == pytest.approx(42.5)
    assert rec_weak.weak_validity is True


def test_signal_score_weak_validity_at_threshold_no_halving() -> None:
    rec = _rec(s1=WEAK_VALIDITY_THRESHOLD)
    assert signal_score(rec) == pytest.approx(86.6667, abs=0.01)
    assert rec.weak_validity is False


def test_signal_score_missing_stage_contributes_zero() -> None:
    rec = _rec(s3=None, s4a=None, s4b=None)
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


# ---------- config_score (per-pattern) ----------

def test_config_score_empty_returns_none() -> None:
    assert config_score([]) is None


def test_config_score_single_record_includes_penalty() -> None:
    """A single record is in low_confidence territory (n<10), so applies penalty."""
    r = _rec()
    signal_score(r)
    score = config_score([r])
    # pattern_score = 100*0.40 + 100*0.25 + (2/5)*100*0.20 + (1/100)*100*0.15
    #               = 40 + 25 + 8 + 0.15 = 73.15, ×0.9 = 65.835
    assert score == pytest.approx(65.835)


def test_config_score_two_records_same_pattern_weighted_mean() -> None:
    r1 = [_rec(net_rr=2.0) for _ in range(6)]          # 100 each
    r2 = [_rec(s3=0, s4a=0, s4b=0, net_rr=1.0) for _ in range(6)]  # 20 each
    recs = r1 + r2
    for r in recs:
        signal_score(r)
    # 12 records, same pattern, no penalty (12 >= 10).
    # avg_score = 60, win_rate = 1.0, avg_rr = 1.5, n=12
    #   = 60*0.40 + 100*0.25 + (1.5/5)*100*0.20 + (12/100)*100*0.15
    #   = 24 + 25 + 6 + 1.8 = 56.8
    assert config_score(recs) == pytest.approx(56.8)


def test_config_score_per_pattern_breakdown() -> None:
    gartley = [_rec(pattern_family="gartley", net_rr=2.0) for _ in range(15)]
    bat = [_rec(pattern_family="bat", s3=0, s4a=0, s4b=0, net_rr=1.0) for _ in range(15)]
    for r in gartley + bat:
        signal_score(r)
    _, _, patterns = config_score_with_patterns(gartley + bat)
    families = [p["pattern_family"] for p in patterns]
    assert families == ["bat", "gartley"]  # sorted
    assert all(p["signal_count"] == 15 for p in patterns)
    gartley_score = next(p for p in patterns if p["pattern_family"] == "gartley")
    bat_score = next(p for p in patterns if p["pattern_family"] == "bat")
    # gartley: 100*0.40 + 1.0*100*0.25 + (2/5)*100*0.20 + (15/100)*100*0.15
    #        = 40 + 25 + 8 + 2.25 = 75.25
    # bat:    20*0.40 + 1.0*100*0.25 + (1/5)*100*0.20 + (15/100)*100*0.15
    #        = 8 + 25 + 4 + 2.25 = 39.25
    assert gartley_score["pattern_score"] == pytest.approx(75.25)
    assert bat_score["pattern_score"] == pytest.approx(39.25)


def test_config_score_weighted_by_signal_count() -> None:
    gartley = [_rec(pattern_family="gartley", net_rr=2.0) for _ in range(20)]
    bat = [_rec(pattern_family="bat", s3=0, s4a=0, s4b=0, net_rr=1.0) for _ in range(15)]
    for r in gartley + bat:
        signal_score(r)
    # gartley score = 76, bat score = 39.25
    # weighted = (76*20 + 39.25*15) / 35 = 60.25
    assert config_score(gartley + bat) == pytest.approx(60.25)


def test_config_score_low_confidence_penalty_when_any_pattern_below_10() -> None:
    gartley = [_rec(pattern_family="gartley", net_rr=2.0) for _ in range(20)]
    bat = [_rec(pattern_family="bat", s3=0, s4a=0, s4b=0, net_rr=1.0) for _ in range(5)]
    for r in gartley + bat:
        signal_score(r)
    # gartley = 76, bat = 20*0.40 + 100*0.25 + (1/5)*20 + (5/100)*15
    #        = 8 + 25 + 4 + 0.75 = 37.75
    # weighted = (76*20 + 37.75*5) / 25 = 68.35
    # ×0.9 = 61.515
    base_score, low_conf, _ = config_score_with_patterns(gartley + bat)
    assert low_conf is True
    assert base_score == pytest.approx(68.35 * 0.9)


def test_config_score_no_low_confidence_when_all_patterns_have_10_plus() -> None:
    gartley = [_rec(pattern_family="gartley") for _ in range(15)]
    bat = [_rec(pattern_family="bat", s3=0, s4a=0, s4b=0) for _ in range(15)]
    for r in gartley + bat:
        signal_score(r)
    _, low_conf, _ = config_score_with_patterns(gartley + bat)
    assert low_conf is False


def test_config_score_no_penalty_at_exactly_10_samples() -> None:
    recs = [_rec(pattern_family="gartley") for _ in range(10)]
    for r in recs:
        signal_score(r)
    _, low_conf, _ = config_score_with_patterns(recs)
    assert low_conf is False


def test_config_score_win_rate_zero_for_all_losses() -> None:
    recs = [
        _rec(pattern_family="gartley", outcome="stoploss", net_rr=-1.0)
        for _ in range(15)
    ]
    for r in recs:
        signal_score(r)
    _, _, patterns = config_score_with_patterns(recs)
    assert patterns[0]["win_rate"] == 0.0


def test_config_score_win_rate_zero_when_undecided() -> None:
    recs = [
        _rec(pattern_family="gartley", outcome="expired", net_rr=None)
        for _ in range(15)
    ]
    for r in recs:
        signal_score(r)
    _, _, patterns = config_score_with_patterns(recs)
    assert patterns[0]["win_rate"] == 0.0


def test_config_score_sample_bonus_caps_at_100() -> None:
    recs = [_rec(pattern_family="gartley", net_rr=2.0) for _ in range(150)]
    for r in recs:
        signal_score(r)
    _, _, patterns = config_score_with_patterns(recs)
    # avg_score=100, win_rate=1.0, avg_rr=2.0, n=150 → (150/100 capped 1)*15 = 15
    # 100*0.40 + 100*0.25 + (2/5)*100*0.20 + 15 = 40+25+8+15 = 88
    assert patterns[0]["pattern_score"] == pytest.approx(88.0)


def test_config_score_avg_rr_caps_at_5() -> None:
    recs = [
        _rec(pattern_family="gartley", net_rr=10.0)
        for _ in range(15)
    ]
    for r in recs:
        signal_score(r)
    _, _, patterns = config_score_with_patterns(recs)
    # avg_rr=10 → min(10/5, 1) = 1.0 → 100 * 0.20 = 20
    # = 40 + 25 + 20 + 2.25 = 87.25
    assert patterns[0]["pattern_score"] == pytest.approx(87.25)


# ---------- bench_total ----------

def test_bench_total_combines() -> None:
    assert bench_total(100.0, 50.0) == pytest.approx(80.0)


def test_bench_total_no_config_falls_back() -> None:
    assert bench_total(70.0, None) == 70.0


def test_bench_total_rounded() -> None:
    assert bench_total(33.0, 25.0) == pytest.approx(29.8)


# ---------- aggregate ----------

def test_aggregate_empty_returns_zero() -> None:
    result = aggregate([])
    assert result["signal_score"] == 0.0
    assert result["config_score"] is None
    assert result["bench_total"] == 0.0
    assert result["weak_validity"] is False
    assert result["low_confidence"] is False
    assert result["n_signals"] == 0
    assert result["n_patterns"] == 0


def test_aggregate_single_record_includes_penalty() -> None:
    rec = _rec()
    result = aggregate([rec])
    assert result["n_signals"] == 1
    assert result["n_patterns"] == 1
    assert result["signal_score"] == 100.0
    assert result["config_score"] == pytest.approx(65.835)
    assert result["bench_total"] == pytest.approx(0.6 * 100 + 0.4 * 65.835)
    assert result["weak_validity"] is False
    assert rec.config_score == pytest.approx(65.835)


def test_aggregate_multiple_records_same_pattern() -> None:
    r1 = [_rec(net_rr=2.0) for _ in range(6)]
    r2 = [_rec(s3=0, s4a=0, s4b=0, net_rr=1.0) for _ in range(3)]
    r3 = [_rec(s1=MAX_STAGE1 / 2, s3=0, s4a=0, net_rr=1.5) for _ in range(3)]
    recs = r1 + r2 + r3
    result = aggregate(recs)
    assert result["n_signals"] == 12
    assert result["n_patterns"] == 1
    # avg_score = 60, win_rate=1.0, avg_rr = (12+3+4.5)/12 = 1.625
    # pattern_score = 60*0.40 + 100*0.25 + (1.625/5)*100*0.20 + (12/100)*100*0.15
    #               = 24 + 25 + 6.5 + 1.8 = 57.3
    assert result["config_score"] == pytest.approx(57.3)


def test_aggregate_marks_weak_validity_if_any_record_is_weak() -> None:
    r1 = _rec()  # strong
    r2 = _rec(s1=2)  # weak
    result = aggregate([r1, r2])
    assert result["weak_validity"] is True


def test_aggregate_writes_config_score_to_all_records() -> None:
    r1 = [_rec(net_rr=2.0) for _ in range(6)]
    r2 = [_rec(s3=0, s4a=0, s4b=0, net_rr=1.0) for _ in range(6)]
    recs = r1 + r2
    aggregate(recs)
    assert recs[0].config_score == recs[-1].config_score


def test_aggregate_writes_bench_total_to_all_records() -> None:
    r1 = [_rec(net_rr=2.0) for _ in range(6)]
    r2 = [_rec(s3=0, s4a=0, s4b=0, net_rr=1.0) for _ in range(6)]
    recs = r1 + r2
    aggregate(recs)
    assert recs[0].bench_total == recs[-1].bench_total


def test_aggregate_idempotent() -> None:
    r1 = [_rec(net_rr=2.0) for _ in range(6)]
    r2 = [_rec(s3=0, s4a=0, s4b=0, net_rr=1.0) for _ in range(6)]
    recs = r1 + r2
    aggregate(recs)
    cfg1 = recs[0].config_score
    aggregate(recs)
    assert recs[0].config_score == cfg1


def test_aggregate_per_pattern_breakdown_in_result() -> None:
    gartley = [_rec(pattern_family="gartley") for _ in range(15)]
    bat = [_rec(pattern_family="bat", s3=0, s4a=0, s4b=0, net_rr=1.0) for _ in range(15)]
    result = aggregate(gartley + bat)
    assert result["n_patterns"] == 2
    families = [p["pattern_family"] for p in result["pattern_scores"]]
    assert families == ["bat", "gartley"]


def test_aggregate_low_confidence_flag_propagates() -> None:
    gartley = [_rec(pattern_family="gartley") for _ in range(15)]
    bat = [_rec(pattern_family="bat", s3=0, s4a=0, s4b=0, net_rr=1.0) for _ in range(5)]
    result = aggregate(gartley + bat)
    assert result["low_confidence"] is True