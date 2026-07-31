"""Tests for bench.scoring.pareto."""

from __future__ import annotations

from app.loop.pareto import ParetoPoint
from bench.scoring.pareto import (
    BENCH_VERSION,
    WEIGHTS_VERSION,
    BenchAugmentedParetoPoint,
)


def _base(**overrides) -> ParetoPoint:
    defaults = dict(
        params_sha="abc123",
        gen=1,
        cluster="harmonic",
        run_dir="/tmp/runs/abc123",
        sharpe=1.5,
        calmar=1.0,
        profit_factor=2.0,
        worst_regime_sharpe=0.5,
        trade_count=100,
        fitness=0.8,
    )
    defaults.update(overrides)
    return ParetoPoint(**defaults)


def test_construction_uses_defaults() -> None:
    p = BenchAugmentedParetoPoint(base=_base())
    assert p.bench_version == BENCH_VERSION
    assert p.weights_version == WEIGHTS_VERSION
    assert p.signal_score == 0.0
    assert p.config_score is None
    assert p.bench_total == 0.0
    assert p.low_confidence is False
    assert p.n_signals == 0
    assert p.win_rate == 0.0
    assert p.win_rate_ci == (0.0, 1.0)
    assert p.exit_code == 0
    assert p.warnings == []


def test_construction_overrides() -> None:
    p = BenchAugmentedParetoPoint(
        base=_base(),
        signal_score=85.0,
        config_score=70.0,
        bench_total=80.0,
        low_confidence=True,
        n_signals=200,
        win_rate=0.65,
        win_rate_ci=(0.55, 0.74),
        exit_code=2,
        warnings=["low sample"],
    )
    assert p.signal_score == 85.0
    assert p.config_score == 70.0
    assert p.bench_total == 80.0
    assert p.low_confidence is True
    assert p.n_signals == 200
    assert p.win_rate == 0.65
    assert p.win_rate_ci == (0.55, 0.74)
    assert p.exit_code == 2
    assert p.warnings == ["low sample"]


def test_composition_not_inheritance() -> None:
    """BenchAugmentedParetoPoint must hold a ParetoPoint by reference,
    not extend it. Otherwise we'd touch app/loop/pareto.py."""
    p = BenchAugmentedParetoPoint(base=_base())
    assert isinstance(p.base, ParetoPoint)
    # The wrapper is NOT a ParetoPoint.
    assert not isinstance(p, ParetoPoint)


def test_each_instance_has_independent_warnings_list() -> None:
    """field(default_factory=list) gives a fresh list per instance."""
    a = BenchAugmentedParetoPoint(base=_base())
    b = BenchAugmentedParetoPoint(base=_base())
    a.warnings.append("foo")
    assert b.warnings == []


def test_to_dict_inlines_base_fields_with_prefix() -> None:
    p = BenchAugmentedParetoPoint(
        base=_base(params_sha="xyz", sharpe=2.5),
        signal_score=70.0,
    )
    d = p.to_dict()
    assert d["base_params_sha"] == "xyz"
    assert d["base_sharpe"] == 2.5
    assert d["base_gen"] == 1
    assert d["signal_score"] == 70.0
    assert d["bench_version"] == BENCH_VERSION
    assert d["weights_version"] == WEIGHTS_VERSION
    # No "base" key — fully inlined.
    assert "base" not in d


def test_to_dict_serialises_all_bench_fields() -> None:
    p = BenchAugmentedParetoPoint(
        base=_base(),
        signal_score=10.0,
        config_score=20.0,
        bench_total=15.0,
        low_confidence=True,
        n_signals=42,
        win_rate=0.5,
        win_rate_ci=(0.4, 0.6),
        exit_code=1,
        warnings=["w"],
    )
    d = p.to_dict()
    for k in (
        "signal_score",
        "config_score",
        "bench_total",
        "low_confidence",
        "n_signals",
        "win_rate",
        "win_rate_ci",
        "exit_code",
        "warnings",
    ):
        assert k in d


def test_version_constants_are_strings() -> None:
    assert isinstance(BENCH_VERSION, str) and BENCH_VERSION
    assert isinstance(WEIGHTS_VERSION, str) and WEIGHTS_VERSION


def test_dataclass_equality() -> None:
    p1 = BenchAugmentedParetoPoint(base=_base())
    p2 = BenchAugmentedParetoPoint(base=_base())
    assert p1 == p2


def test_to_dict_with_none_config_score() -> None:
    p = BenchAugmentedParetoPoint(base=_base(), config_score=None)
    d = p.to_dict()
    assert d["config_score"] is None
