"""Tests for bench.dataset.dataset_builder."""

from __future__ import annotations

import pytest

from bench.dataset.dataset_builder import (
    assign_split,
    boundary_discount,
    find_boundary_crossings,
    partition_by_split,
    split_boundary,
)
from bench.dataset.signal_record import empty_record


# ---------- split_boundary ----------

def test_split_boundary_basic() -> None:
    assert split_boundary(100, 0.7) == 70
    assert split_boundary(100, 0.5) == 50
    assert split_boundary(100, 0.95) == 95


def test_split_boundary_clamps_to_last_bar() -> None:
    """Boundary is always strictly less than total_bars given validated inputs."""
    assert split_boundary(100, 0.99) == 99
    assert split_boundary(100, 0.999) == 99
    assert split_boundary(2, 0.99) == 1
    # The strongest case: is_ratio=0.9999 on 100 bars → 99, not 100
    assert split_boundary(100, 0.9999) == 99


def test_split_boundary_zero_or_negative_total_raises() -> None:
    with pytest.raises(ValueError):
        split_boundary(0, 0.7)
    with pytest.raises(ValueError):
        split_boundary(-5, 0.7)


def test_split_boundary_invalid_ratio_raises() -> None:
    with pytest.raises(ValueError):
        split_boundary(100, 0.0)
    with pytest.raises(ValueError):
        split_boundary(100, 1.0)
    with pytest.raises(ValueError):
        split_boundary(100, -0.1)
    with pytest.raises(ValueError):
        split_boundary(100, 1.5)


# ---------- assign_split ----------

def test_assign_split_is_when_index_leq_boundary() -> None:
    recs = [
        empty_record(signal_id="a"),
        empty_record(signal_id="b"),
        empty_record(signal_id="c"),
    ]
    bar_index_of = {"a": 10, "b": 50, "c": 80}
    n = assign_split(recs, bar_index_of, boundary=50)
    assert n == 3
    assert recs[0].split == "is"
    assert recs[1].split == "is"  # boundary inclusive
    assert recs[2].split == "oos"


def test_assign_split_skips_missing_ids() -> None:
    recs = [
        empty_record(signal_id="a"),
        empty_record(signal_id="b"),
    ]
    bar_index_of = {"a": 10}  # "b" missing
    n = assign_split(recs, bar_index_of, boundary=50)
    assert n == 1
    assert recs[0].split == "is"
    assert recs[1].split is None


def test_assign_split_empty_records() -> None:
    assert assign_split([], {}, boundary=10) == 0


# ---------- find_boundary_crossings ----------

def test_find_crossings_marks_is_entry_to_oos_exit() -> None:
    recs = [
        empty_record(signal_id="a"),  # entry 40, horizon 10 → exit 49 — pure IS
        empty_record(signal_id="b"),  # entry 40, horizon 21 → exit 60 — crosses
        empty_record(signal_id="c"),  # entry 80, horizon 10 → exit 89 — pure OOS
    ]
    bar_index_of = {"a": 40, "b": 40, "c": 80}
    horizon_of = {"a": 10, "b": 21, "c": 10}
    n = find_boundary_crossings(recs, bar_index_of, boundary=50, horizon_of=horizon_of)
    assert n == 1
    assert recs[0].crosses_boundary is False  # exits at 49, all IS
    assert recs[0].boundary_distance_bars is None
    assert recs[1].crosses_boundary is True   # exits at 60, OOS bars 51..60
    assert recs[1].boundary_distance_bars == 10
    assert recs[2].crosses_boundary is False  # entry 80 already OOS
    assert recs[2].boundary_distance_bars is None


def test_find_crossings_uniform_horizon_applies_to_all() -> None:
    """When horizon_of is None, the uniform horizon is applied to all records."""
    recs = [
        empty_record(signal_id="a"),  # entry 40, h=11 → exit 50, last IS bar — no cross
        empty_record(signal_id="b"),  # entry 41, h=11 → exit 51, crosses
    ]
    bar_index_of = {"a": 40, "b": 41}
    n = find_boundary_crossings(recs, bar_index_of, boundary=50, horizon=11)
    assert n == 1
    assert recs[0].crosses_boundary is False
    assert recs[1].crosses_boundary is True
    assert recs[1].boundary_distance_bars == 1


def test_find_crossings_requires_horizon() -> None:
    with pytest.raises(ValueError):
        find_boundary_crossings([], {}, boundary=50)


def test_find_crossings_uniform_horizon_must_be_positive() -> None:
    with pytest.raises(ValueError):
        find_boundary_crossings([], {}, boundary=50, horizon=0)
    with pytest.raises(ValueError):
        find_boundary_crossings([], {}, boundary=50, horizon=-1)


def test_find_crossings_per_record_horizon_overrides_uniform() -> None:
    recs = [
        empty_record(signal_id="a"),  # per-record horizon=5 → exit 44, no cross
        empty_record(signal_id="b"),  # per-record horizon=20 → exit 59, crosses
    ]
    bar_index_of = {"a": 40, "b": 40}
    horizon_of = {"a": 5, "b": 20}
    n = find_boundary_crossings(
        recs, bar_index_of, boundary=50, horizon=30, horizon_of=horizon_of
    )
    assert n == 1
    assert recs[0].crosses_boundary is False
    assert recs[1].crosses_boundary is True
    assert recs[1].boundary_distance_bars == 9


def test_find_crossings_per_record_horizon_missing_id_safe() -> None:
    """When per-record horizon is missing for a record, that record is skipped safely."""
    recs = [
        empty_record(signal_id="a"),
        empty_record(signal_id="b"),  # "b" not in horizon_of
    ]
    bar_index_of = {"a": 40, "b": 40}
    horizon_of = {"a": 5}  # "b" missing
    n = find_boundary_crossings(recs, bar_index_of, boundary=50, horizon_of=horizon_of)
    # "a" doesn't cross (h=5, exit=44); "b" is skipped safely
    assert n == 0
    assert recs[0].crosses_boundary is False
    assert recs[1].crosses_boundary is False


def test_find_crossings_entry_exactly_at_boundary_plus_one() -> None:
    """Entry just past the boundary is fully OOS, not a crossing."""
    recs = [empty_record(signal_id="a")]
    bar_index_of = {"a": 51}
    n = find_boundary_crossings(recs, bar_index_of, boundary=50, horizon=10)
    assert n == 0
    assert recs[0].crosses_boundary is False


def test_find_crossings_exit_exactly_at_boundary() -> None:
    """Exit bar == boundary is the last IS bar, not a crossing."""
    recs = [empty_record(signal_id="a")]
    bar_index_of = {"a": 41}
    n = find_boundary_crossings(recs, bar_index_of, boundary=50, horizon=10)
    assert n == 0


def test_find_crossings_missing_id_marked_safe() -> None:
    recs = [empty_record(signal_id="missing")]
    n = find_boundary_crossings(recs, {}, boundary=50, horizon=10)
    assert n == 0
    assert recs[0].crosses_boundary is False


# ---------- boundary_discount ----------

def test_discount_no_crossing_returns_one() -> None:
    rec = empty_record()
    rec.crosses_boundary = False
    assert boundary_discount(rec, horizon=30) == 1.0


def test_discount_partial_crossing() -> None:
    rec = empty_record()
    rec.crosses_boundary = True
    rec.boundary_distance_bars = 5
    # 1 - 5/30 = 0.833...
    assert boundary_discount(rec, horizon=30) == pytest.approx(0.8333, abs=1e-3)


def test_discount_full_crossing_clamps_to_zero() -> None:
    rec = empty_record()
    rec.crosses_boundary = True
    rec.boundary_distance_bars = 30  # boundary_distance >= horizon
    assert boundary_discount(rec, horizon=30) == 0.0


def test_discount_clamped_when_boundary_distance_exceeds_horizon() -> None:
    rec = empty_record()
    rec.crosses_boundary = True
    rec.boundary_distance_bars = 50
    assert boundary_discount(rec, horizon=30) == 0.0


def test_discount_zero_horizon_returns_one() -> None:
    rec = empty_record()
    rec.crosses_boundary = True
    rec.boundary_distance_bars = 5
    assert boundary_discount(rec, horizon=0) == 1.0


def test_discount_no_boundary_distance_recorded() -> None:
    rec = empty_record()
    rec.crosses_boundary = True
    rec.boundary_distance_bars = None
    assert boundary_discount(rec, horizon=30) == 1.0


# ---------- partition_by_split ----------

def test_partition_splits_into_two_lists() -> None:
    recs = [
        empty_record(signal_id="a", ),
        empty_record(signal_id="b"),
        empty_record(signal_id="c"),
        empty_record(signal_id="d"),
    ]
    recs[0].split = "is"
    recs[1].split = "oos"
    recs[2].split = "is"
    recs[3].split = None  # dropped
    is_recs, oos_recs = partition_by_split(recs)
    assert [r.signal_id for r in is_recs] == ["a", "c"]
    assert [r.signal_id for r in oos_recs] == ["b"]


def test_partition_empty_input() -> None:
    is_recs, oos_recs = partition_by_split([])
    assert is_recs == []
    assert oos_recs == []


def test_partition_all_one_side() -> None:
    recs = [
        empty_record(signal_id="a"),
        empty_record(signal_id="b"),
    ]
    for r in recs:
        r.split = "oos"
    is_recs, oos_recs = partition_by_split(recs)
    assert is_recs == []
    assert [r.signal_id for r in oos_recs] == ["a", "b"]
