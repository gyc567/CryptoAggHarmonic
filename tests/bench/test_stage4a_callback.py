"""Tests for bench.pipeline.stage4a_callback."""

from __future__ import annotations

from bench.dataset.signal_record import empty_record
from bench.pipeline.stage4a_callback import (
    _buffer_consumption,
    _depth_subscore,
    _mae_mfe_subscore,
    _stop_buffer_subscore,
    _time_subscore,
    _volume_subscore,
    stage4a_score,
)


def _filled(
    *,
    direction: str = "long",
    entry_price: float = 100,
    stop_price: float = 95,
    atr_at_entry: float = 2.0,
    mae: float | None = 0.5,
    mfe: float | None = 5.0,
    callback_depth: float | None = 0.25,
    callback_bars: int | None = 2,
    bars_held: int | None = 10,
    callback_volume_ratio: float | None = 0.7,
):
    return empty_record(
        direction=direction,
        entry_price=entry_price,
        stop_price=stop_price,
        atr_at_entry=atr_at_entry,
        mae=mae,
        mfe=mfe,
        callback_depth=callback_depth,
        callback_bars=callback_bars,
        bars_held=bars_held,
        callback_volume_ratio=callback_volume_ratio,
    )


# ---------- _mae_mfe_subscore ----------

def test_mae_mfe_none_returns_zero() -> None:
    assert _mae_mfe_subscore(None, None) == 0.0
    assert _mae_mfe_subscore(1.0, None) == 0.0
    assert _mae_mfe_subscore(None, 5.0) == 0.0


def test_mae_mfe_full_marks() -> None:
    assert _mae_mfe_subscore(1.0, 10.0) == 6.0  # 0.1 ratio


def test_mae_mfe_tier_buckets() -> None:
    # ratio thresholds (per docstring): <0.2:6, <0.4:4, <0.6:2, else 0
    # NOTE: the code uses < (strict), so 0.2 falls into the <0.4 bucket.
    assert _mae_mfe_subscore(2.0, 10.0) == 4.0   # 0.2 → <0.4 bucket
    assert _mae_mfe_subscore(3.0, 10.0) == 4.0   # 0.3
    assert _mae_mfe_subscore(5.0, 10.0) == 2.0   # 0.5 → <0.6 bucket
    assert _mae_mfe_subscore(6.0, 10.0) == 0.0   # 0.6 → else bucket
    assert _mae_mfe_subscore(7.0, 10.0) == 0.0   # > 0.6


def test_mae_mfe_zero_mfe_assumed_one() -> None:
    # mfe=0 → ratio treated as 1.0 → 0 marks
    assert _mae_mfe_subscore(1.0, 0.0) == 0.0


# ---------- _depth_subscore ----------

def test_depth_none_returns_zero() -> None:
    assert _depth_subscore(None) == 0.0


def test_depth_tiers() -> None:
    assert _depth_subscore(0.29) == 5.0
    assert _depth_subscore(0.59) == 3.0
    assert _depth_subscore(0.99) == 1.0
    assert _depth_subscore(1.5) == 0.0


# ---------- _time_subscore ----------

def test_time_none_returns_zero() -> None:
    assert _time_subscore(None, 10) == 0.0
    assert _time_subscore(2, None) == 0.0
    assert _time_subscore(2, 0) == 0.0


def test_time_tiers() -> None:
    # ratio thresholds: <0.2:3, <0.4:2, <0.6:1, >=0.6:0
    # strict < means 0.2 falls into <0.4 bucket
    assert _time_subscore(1, 10) == 3.0   # 0.1
    assert _time_subscore(2, 10) == 2.0   # 0.2 → <0.4
    assert _time_subscore(3, 10) == 2.0   # 0.3
    assert _time_subscore(4, 10) == 1.0   # 0.4 → <0.6
    assert _time_subscore(5, 10) == 1.0   # 0.5
    assert _time_subscore(6, 10) == 0.0   # 0.6 → else
    assert _time_subscore(7, 10) == 0.0   # 0.7


# ---------- _volume_subscore ----------

def test_volume_none_returns_zero() -> None:
    assert _volume_subscore(None) == 0.0


def test_volume_tiers() -> None:
    assert _volume_subscore(0.5) == 3.0   # 缩量
    assert _volume_subscore(0.79) == 3.0
    assert _volume_subscore(0.8) == 2.0
    assert _volume_subscore(1.0) == 2.0
    assert _volume_subscore(1.2) == 2.0
    assert _volume_subscore(1.5) == 0.0   # 放量


# ---------- _stop_buffer_subscore ----------

def test_stop_buffer_none_returns_zero() -> None:
    assert _stop_buffer_subscore(None) == 0.0


def test_stop_buffer_tiers() -> None:
    assert _stop_buffer_subscore(0.29) == 3.0
    assert _stop_buffer_subscore(0.59) == 2.0
    assert _stop_buffer_subscore(0.89) == 1.0
    assert _stop_buffer_subscore(0.95) == 0.0


# ---------- _buffer_consumption ----------

def test_buffer_consumption_basic() -> None:
    rec = _filled(mae=1.0, entry_price=100, stop_price=95, atr_at_entry=2.0)
    # risk = |100 - 95| = 5; buffer = 1 / 5 = 0.2
    assert _buffer_consumption(rec) == 0.2


def test_buffer_consumption_short() -> None:
    rec = _filled(direction="short", mae=2.0, entry_price=100, stop_price=105, atr_at_entry=2.0)
    # risk = |100 - 105| = 5; buffer = 2 / 5 = 0.4
    assert _buffer_consumption(rec) == 0.4


def test_buffer_consumption_none_when_no_mae() -> None:
    rec = _filled(mae=None)
    assert _buffer_consumption(rec) is None


def test_buffer_consumption_none_when_no_atr() -> None:
    rec = _filled(atr_at_entry=None)
    assert _buffer_consumption(rec) is None


def test_buffer_consumption_none_when_zero_risk() -> None:
    rec = _filled(entry_price=100, stop_price=100, atr_at_entry=2.0)
    assert _buffer_consumption(rec) is None


def test_buffer_consumption_none_when_zero_atr() -> None:
    rec = _filled(atr_at_entry=0.0)
    assert _buffer_consumption(rec) is None


# ---------- stage4a_score integration ----------

def test_stage4a_perfect_score_20() -> None:
    rec = _filled(
        mae=1.0, mfe=10.0,          # ratio 0.1 → <0.2 → 6
        callback_depth=0.1,         # <0.3 → 5
        callback_bars=1, bars_held=10,  # 0.1 → <0.2 → 3
        callback_volume_ratio=0.5,  # <0.8 → 3 (缩量)
    )
    # buffer = mae/risk = 1/5 = 0.2 → <0.3 → 3
    total = stage4a_score(rec)
    assert total == 20.0
    assert rec.stage4a_score == 20.0


def test_stage4a_zero_score() -> None:
    rec = _filled(
        mae=10.0, mfe=10.0,         # ratio 1.0 → else → 0
        callback_depth=2.0,         # >=1.0 → 0
        callback_bars=8, bars_held=10,  # 0.8 → else → 0
        callback_volume_ratio=2.0,  # >1.2 → 0 (放量)
    )
    # buffer = mae/risk = 10/5 = 2.0 → >=0.9 → 0
    total = stage4a_score(rec)
    assert total == 0.0
    assert rec.stage4a_score == 0.0


def test_stage4a_missing_fields_returns_zero_per_subscore() -> None:
    rec = empty_record(direction="long", entry_price=100, stop_price=95, atr_at_entry=2.0)
    # all callback fields default None
    total = stage4a_score(rec)
    assert total == 0.0


def test_stage4a_mutates_record() -> None:
    rec = _filled()
    stage4a_score(rec)
    assert hasattr(rec, "stage4a_score")
    assert isinstance(rec.stage4a_score, float)


def test_stage4a_returns_same_value_as_stored() -> None:
    rec = _filled()
    assert stage4a_score(rec) == rec.stage4a_score
