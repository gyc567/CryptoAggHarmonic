"""Tests for bench.pipeline.stage3_outcome."""

from __future__ import annotations

from bench.dataset.signal_record import empty_record
from bench.pipeline.stage3_outcome import (
    _efficiency_subscore,
    _result_subscore,
    _rr_subscore,
    _stop_hit_penalty,
    stage3_score,
)


# ---------- _result_subscore ----------

def test_result_tp3_full() -> None:
    assert _result_subscore("tp3") == 25.0


def test_result_tp2() -> None:
    assert _result_subscore("tp2") == 20.0


def test_result_tp1() -> None:
    assert _result_subscore("tp1") == 15.0


def test_result_breakeven() -> None:
    assert _result_subscore("breakeven") == 8.0


def test_result_stoploss_zero() -> None:
    assert _result_subscore("stoploss") == 0.0


def test_result_expired_zero() -> None:
    assert _result_subscore("expired") == 0.0


def test_result_incomplete_zero() -> None:
    assert _result_subscore("incomplete") == 0.0


# ---------- _rr_subscore ----------

def test_rr_above_3_full() -> None:
    assert _rr_subscore(3.5) == 10.0
    assert _rr_subscore(3.0) == 10.0


def test_rr_between_2_and_3() -> None:
    assert _rr_subscore(2.5) == 7.0
    assert _rr_subscore(2.0) == 7.0


def test_rr_between_1_and_2() -> None:
    assert _rr_subscore(1.5) == 4.0
    assert _rr_subscore(1.0) == 4.0


def test_rr_between_0_5_and_1() -> None:
    assert _rr_subscore(0.7) == 2.0
    assert _rr_subscore(0.5) == 2.0


def test_rr_below_0_5_zero() -> None:
    assert _rr_subscore(0.3) == 0.0
    assert _rr_subscore(0.0) == 0.0
    assert _rr_subscore(-1.0) == 0.0


def test_rr_none_zero() -> None:
    assert _rr_subscore(None) == 0.0


# ---------- _efficiency_subscore ----------

def test_efficiency_high() -> None:
    assert _efficiency_subscore(empty_record(price_efficiency=0.9)) == 10.0
    assert _efficiency_subscore(empty_record(price_efficiency=0.8)) == 10.0


def test_efficiency_mid() -> None:
    assert _efficiency_subscore(empty_record(price_efficiency=0.6)) == 6.0
    assert _efficiency_subscore(empty_record(price_efficiency=0.5)) == 6.0


def test_efficiency_low() -> None:
    assert _efficiency_subscore(empty_record(price_efficiency=0.4)) == 3.0
    assert _efficiency_subscore(empty_record(price_efficiency=0.3)) == 3.0


def test_efficiency_floor_one() -> None:
    assert _efficiency_subscore(empty_record(price_efficiency=0.1)) == 1.0
    # 0.0 is the explicit stop-loss floor per v3 spec
    assert _efficiency_subscore(empty_record(price_efficiency=0.0)) == 1.0


def test_efficiency_none_zero() -> None:
    assert _efficiency_subscore(empty_record(price_efficiency=None)) == 0.0


# ---------- _stop_hit_penalty ----------

def test_stop_hit_penalty_applied() -> None:
    assert _stop_hit_penalty(empty_record(hit_stop_before_tp=True)) == -5.0


def test_stop_hit_penalty_not_applied() -> None:
    assert _stop_hit_penalty(empty_record(hit_stop_before_tp=False)) == 0.0
    assert _stop_hit_penalty(empty_record(hit_stop_before_tp=None)) == 0.0


# ---------- stage3_score (integration) ----------

def test_stage3_no_outcome_zero() -> None:
    rec = empty_record(outcome=None)
    score = stage3_score(rec)
    assert score == 0.0
    assert rec.stage3_score == 0.0


def test_stage3_perfect_tp3_no_penalty() -> None:
    rec = empty_record(
        outcome="tp3", net_rr=3.5, price_efficiency=0.9, hit_stop_before_tp=False
    )
    score = stage3_score(rec)
    assert score == 25.0 + 10.0 + 10.0 + 0.0


def test_stage3_stoploss_with_penalty() -> None:
    rec = empty_record(
        outcome="stoploss", net_rr=-1.0, price_efficiency=0.0, hit_stop_before_tp=True
    )
    score = stage3_score(rec)
    assert score == 0.0 + 0.0 + 1.0 + (-5.0)


def test_stage3_score_recorded_on_record() -> None:
    rec = empty_record(outcome="tp1", net_rr=1.5, price_efficiency=0.5)
    stage3_score(rec)
    assert rec.stage3_score == 15.0 + 4.0 + 6.0 + 0.0
