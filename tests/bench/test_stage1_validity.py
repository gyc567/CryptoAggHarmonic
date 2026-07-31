"""Tests for bench.pipeline.stage1_validity."""

from __future__ import annotations

from bench.dataset.signal_record import empty_record
from bench.pipeline.stage1_validity import (
    _data_subscore,
    _entry_zone_subscore,
    _geometric_subscore,
    _prz_subscore,
    _stop_subscore,
    stage1_score,
)


# ---------- _geometric_subscore ----------

def test_geometric_zero_prz_full_marks() -> None:
    rec = empty_record(prz_width_atr=0.0)
    assert _geometric_subscore(rec) == 4.0


def test_geometric_one_atr_zero_marks() -> None:
    rec = empty_record(prz_width_atr=1.0)
    assert _geometric_subscore(rec) == 0.0


def test_geometric_above_one_clamped() -> None:
    rec = empty_record(prz_width_atr=2.0)
    assert _geometric_subscore(rec) == 0.0


def test_geometric_negative_prz_full_marks() -> None:
    rec = empty_record(prz_width_atr=-0.5)
    assert _geometric_subscore(rec) == 4.0


def test_geometric_linear_mid() -> None:
    rec = empty_record(prz_width_atr=0.5)
    assert _geometric_subscore(rec) == 2.0


# ---------- _prz_subscore ----------

def test_prz_lt_0_5_full() -> None:
    assert _prz_subscore(empty_record(prz_width_atr=0.4)) == 2.0


def test_prz_lt_1_one_point() -> None:
    assert _prz_subscore(empty_record(prz_width_atr=0.7)) == 1.0


def test_prz_ge_1_zero() -> None:
    assert _prz_subscore(empty_record(prz_width_atr=1.5)) == 0.0


# ---------- _stop_subscore ----------

def test_stop_optimal_range_full() -> None:
    # sd_atr = 2.0 → full marks
    rec = empty_record(entry_price=100, stop_price=96, atr_at_entry=2.0)
    assert _stop_subscore(rec) == 2.0


def test_stop_lower_bound() -> None:
    # sd_atr = 0.5 → still full marks
    rec = empty_record(entry_price=100, stop_price=99, atr_at_entry=2.0)
    assert _stop_subscore(rec) == 2.0


def test_stop_too_tight_linear_decay() -> None:
    # sd_atr = 0.25 → 2.0 * (0.25/0.5) = 1.0
    rec = empty_record(entry_price=100, stop_price=99.5, atr_at_entry=2.0)
    assert _stop_subscore(rec) == 1.0


def test_stop_too_wide_linear_decay() -> None:
    # sd_atr = 4.5 → 2 * (1 - (4.5-3)/3) = 2 * (1 - 0.5) = 1.0
    rec = empty_record(entry_price=100, stop_price=91, atr_at_entry=2.0)
    assert _stop_subscore(rec) == 1.0


def test_stop_extreme_clamped_to_zero() -> None:
    # sd_atr = 8.0 → 2 * (1 - 5/3) = 2 * (-2/3) — clamped to 0
    rec = empty_record(entry_price=100, stop_price=84, atr_at_entry=2.0)
    assert _stop_subscore(rec) == 0.0


def test_stop_zero_atr_zero_marks() -> None:
    rec = empty_record(entry_price=100, stop_price=95, atr_at_entry=0.0)
    assert _stop_subscore(rec) == 0.0


# ---------- _data_subscore ----------

def test_data_long_correct_full_marks() -> None:
    rec = empty_record(direction="long", entry_price=100, stop_price=95, tp1=110)
    assert _data_subscore(rec) == 2.0


def test_data_long_inverted_zero() -> None:
    rec = empty_record(direction="long", entry_price=100, stop_price=110, tp1=95)
    assert _data_subscore(rec) == 0.0


def test_data_short_correct_full_marks() -> None:
    rec = empty_record(direction="short", entry_price=100, stop_price=105, tp1=90)
    assert _data_subscore(rec) == 2.0


def test_data_short_inverted_zero() -> None:
    rec = empty_record(direction="short", entry_price=100, stop_price=95, tp1=110)
    assert _data_subscore(rec) == 0.0


def test_data_zero_prices_zero() -> None:
    rec = empty_record(entry_price=0, stop_price=0, tp1=0)
    assert _data_subscore(rec) == 0.0


def test_data_negative_prices_zero() -> None:
    rec = empty_record(entry_price=-1, stop_price=-2, tp1=-3)
    assert _data_subscore(rec) == 0.0


# ---------- _entry_zone_subscore ----------

def test_entry_zone_in_range_full() -> None:
    assert _entry_zone_subscore(empty_record(entry_offset_atr=0.0)) == 2.0
    assert _entry_zone_subscore(empty_record(entry_offset_atr=0.5)) == 2.0
    assert _entry_zone_subscore(empty_record(entry_offset_atr=-1.0)) == 2.0


def test_entry_zone_linear_decay() -> None:
    # +1.0 → 2.0 - (1.0 - 0.5) = 1.5
    assert _entry_zone_subscore(empty_record(entry_offset_atr=1.0)) == 1.5


def test_entry_zone_above_1_5_zero() -> None:
    assert _entry_zone_subscore(empty_record(entry_offset_atr=2.0)) == 0.0


# ---------- stage1_score (integration) ----------

def test_stage1_perfect_signal_full_marks_not_weak() -> None:
    rec = empty_record(
        prz_width_atr=0.1,  # geometric 3.6, prz 2
        entry_price=100, stop_price=96, atr_at_entry=2.0,  # stop 2
        tp1=110,  # data 2
        entry_offset_atr=0.0,  # entry_zone 2
    )
    score, weak = stage1_score(rec)
    assert score == 11.6
    assert weak is False
    assert rec.stage1_score == 11.6
    assert rec.weak_validity is False


def test_stage1_weak_signal_labeled() -> None:
    """Total < 4 → weak_validity=True."""
    rec = empty_record(
        prz_width_atr=2.0,  # geometric 0, prz 0
        entry_price=100, stop_price=50, atr_at_entry=2.0,  # extreme stop, ~0
        tp1=110,
        entry_offset_atr=3.0,  # entry_zone 0
    )
    score, weak = stage1_score(rec)
    assert score == 2.0  # only data subscore contributes
    assert weak is True
    assert rec.weak_validity is True


def test_stage1_boundary_at_4_weak() -> None:
    """Score exactly 4 is NOT weak (the rule is < 4)."""
    rec = empty_record(
        prz_width_atr=1.0,  # geometric 0, prz 0
        entry_price=100, stop_price=99.5, atr_at_entry=2.0,  # stop 1
        tp1=110,  # data 2
        entry_offset_atr=0.5,  # entry_zone 2
    )
    # 0 + 0 + 1 + 2 + 2 = 5 → not weak
    score, weak = stage1_score(rec)
    assert score == 5.0
    assert weak is False
