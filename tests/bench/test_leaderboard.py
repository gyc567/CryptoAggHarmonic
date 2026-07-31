"""Tests for bench.report.leaderboard."""

from __future__ import annotations

import json
import os

import pytest

from app.loop.pareto import ParetoPoint
from bench.report.leaderboard import (
    leaderboard_dict,
    leaderboard_string,
    write_leaderboard,
)
from bench.scoring.pareto import BENCH_VERSION, WEIGHTS_VERSION, BenchAugmentedParetoPoint


def _point(**overrides) -> BenchAugmentedParetoPoint:
    base = ParetoPoint(
        params_sha="abc",
        gen=1,
        cluster="harmonic",
        run_dir="/tmp/x",
        sharpe=1.5,
        calmar=1.0,
        profit_factor=2.0,
        worst_regime_sharpe=0.5,
        trade_count=100,
        fitness=0.8,
    )
    defaults = dict(base=base)
    defaults.update(overrides)
    return BenchAugmentedParetoPoint(**defaults)


# ---------- leaderboard_dict ----------

def test_leaderboard_dict_has_v3_schema_fields() -> None:
    d = leaderboard_dict([_point()], low_confidence=False)
    for k in (
        "bench_version",
        "weights_version",
        "exit_code",
        "low_confidence",
        "comparisons",
        "warnings",
        "n_points",
        "points",
        "extra",
    ):
        assert k in d


def test_leaderboard_dict_versions() -> None:
    d = leaderboard_dict([], low_confidence=True)
    assert d["bench_version"] == BENCH_VERSION
    assert d["weights_version"] == WEIGHTS_VERSION


def test_leaderboard_dict_empty_defaults() -> None:
    d = leaderboard_dict([], low_confidence=False)
    assert d["n_points"] == 0
    assert d["points"] == []
    assert d["comparisons"] == []
    assert d["warnings"] == []
    assert d["extra"] == {}


def test_leaderboard_dict_comparisons_and_warnings() -> None:
    d = leaderboard_dict(
        [_point()],
        low_confidence=True,
        comparisons=[0.01, 0.04, 0.5],
        warnings=["low sample"],
        exit_code=2,
    )
    assert d["comparisons"] == [0.01, 0.04, 0.5]
    assert d["warnings"] == ["low sample"]
    assert d["exit_code"] == 2
    assert d["low_confidence"] is True


def test_leaderboard_dict_serializes_points() -> None:
    d = leaderboard_dict([_point(signal_score=80.0)], low_confidence=False)
    assert d["n_points"] == 1
    assert d["points"][0]["signal_score"] == 80.0
    assert d["points"][0]["base_params_sha"] == "abc"


def test_leaderboard_dict_extra_passthrough() -> None:
    d = leaderboard_dict([], low_confidence=False, extra={"foo": "bar"})
    assert d["extra"] == {"foo": "bar"}


# ---------- write_leaderboard ----------

def test_write_leaderboard_creates_file(tmp_path) -> None:
    out = tmp_path / "leaderboard.json"
    doc = write_leaderboard(
        str(out),
        [_point()],
        low_confidence=False,
    )
    assert out.exists()
    on_disk = json.loads(out.read_text())
    # JSON tuples → lists on disk; compare via key set + scalar fields.
    assert on_disk["bench_version"] == doc["bench_version"]
    assert on_disk["n_points"] == doc["n_points"]
    assert on_disk["low_confidence"] == doc["low_confidence"]
    assert on_disk["points"][0]["signal_score"] == doc["points"][0]["signal_score"]


def test_write_leaderboard_is_valid_json(tmp_path) -> None:
    out = tmp_path / "leaderboard.json"
    write_leaderboard(
        str(out),
        [_point(signal_score=42)],
        low_confidence=False,
        warnings=["w1"],
    )
    data = json.loads(out.read_text())
    assert data["points"][0]["signal_score"] == 42
    assert data["warnings"] == ["w1"]


# ---------- leaderboard_string ----------

def test_leaderboard_string_returns_valid_json() -> None:
    s = leaderboard_string([_point()], low_confidence=False)
    data = json.loads(s)
    assert data["bench_version"] == BENCH_VERSION


def test_leaderboard_string_empty() -> None:
    s = leaderboard_string([], low_confidence=True)
    data = json.loads(s)
    assert data["n_points"] == 0
    assert data["low_confidence"] is True
