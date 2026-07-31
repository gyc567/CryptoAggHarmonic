"""Tests for bench.pipeline.stage4b_technical."""

from __future__ import annotations

from bench.dataset.signal_record import empty_record
from bench.pipeline.stage4b_technical import (
    _confluence_subscore,
    _grade_subscore,
    _stability_subscore,
    stage4b_score,
)


def test_grade_a() -> None:
    assert _grade_subscore("A") == 4.0


def test_grade_b() -> None:
    assert _grade_subscore("B") == 2.0


def test_grade_c() -> None:
    assert _grade_subscore("C") == 0.0


def test_confluence_three_or_more() -> None:
    assert _confluence_subscore(3) == 3.0
    assert _confluence_subscore(5) == 3.0


def test_confluence_two() -> None:
    assert _confluence_subscore(2) == 2.0


def test_confluence_one() -> None:
    assert _confluence_subscore(1) == 1.0


def test_confluence_zero() -> None:
    assert _confluence_subscore(0) == 0.0
    assert _confluence_subscore(-1) == 0.0


def test_stability_stable() -> None:
    assert _stability_subscore("stable") == 3.0


def test_stability_mixed() -> None:
    assert _stability_subscore("mixed") == 1.0


def test_stability_unstable() -> None:
    assert _stability_subscore("unstable") == 0.0


def test_stability_unknown() -> None:
    assert _stability_subscore("") == 0.0
    assert _stability_subscore("garbage") == 0.0


def test_stage4b_perfect() -> None:
    rec = empty_record(grade="A", confluence_score=3, stability_verdict="stable")
    score = stage4b_score(rec)
    assert score == 10.0
    assert rec.stage4b_score == 10.0


def test_stage4b_minimum() -> None:
    rec = empty_record(grade="C", confluence_score=0, stability_verdict="unstable")
    score = stage4b_score(rec)
    assert score == 0.0
