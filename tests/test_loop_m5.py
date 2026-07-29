"""Tests for M5 — walk-forward + regime-bucket aggregation + OOS validation.

Aggregation logic is exercised directly with hand-built metric blobs
(no subprocess); the orchestration tests mock :func:`run_candidate` so
we can validate the quarter-by-quarter flow without invoking the real
v3 harness.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from app.config.tuning import TUNING
from app.loop.worker import CandidateResult
from app.loop.walk_forward import (
    WalkForwardAggregate,
    aggregate,
    list_quarters,
    load_walk_forward,
    save_walk_forward,
    walk_forward,
)
from app.loop.regime_buckets import RegimeAggregate, aggregate_regimes
from app.loop.oos_validator import OOSVerdict, oos_validate


# --- walk_forward.py ---------------------------------------------------------


class TestListQuarters:
    def test_default_2024_2025(self):
        qs = list_quarters(2024, 8)
        assert qs[0] == "2024-Q1"
        assert qs[-1] == "2025-Q4"
        assert len(qs) == 8

    def test_n_quarters(self):
        qs = list_quarters(2024, 4)
        assert len(qs) == 4


def _mkm(quarter: str, sharpe: float, trades: int = 30) -> dict:
    """Build a minimal metrics blob for one quarter."""
    return {
        "__candidate_id__": "c1",
        "__quarter__": quarter,
        "sharpe": sharpe, "calmar": 1.0, "profit_factor": 2.0,
        "trades_count": trades,
        "by_regime": {"bull": {"n": trades // 3, "sharpe": sharpe + 0.1},
                      "bear": {"n": trades // 3, "sharpe": sharpe - 0.1},
                      "range": {"n": trades // 3, "sharpe": sharpe}},
    }


class TestAggregate:
    def test_empty_returns_unknown(self):
        agg = aggregate([])
        assert agg.candidate_id == "?"
        assert agg.quarters == []

    def test_means_match(self):
        per_q = [
            ("2024-Q1", _mkm("2024-Q1", 0.4)),
            ("2024-Q2", _mkm("2024-Q2", 0.6)),
        ]
        agg = aggregate(per_q, oos_quarter="2024-Q2")
        assert agg.mean_sharpe == pytest.approx(0.5)
        assert agg.worst_quarter_sharpe == pytest.approx(0.4)
        assert agg.oos_quarter == "2024-Q2"
        assert agg.oos_sharpe == pytest.approx(0.6)
        assert agg.oos_collapse is False

    def test_oos_collapse_negative(self):
        per_q = [
            ("2024-Q1", _mkm("2024-Q1", 0.5)),
            ("2024-Q2", _mkm("2024-Q2", -0.3)),  # OOS collapses
        ]
        agg = aggregate(per_q, oos_quarter="2024-Q2")
        assert agg.oos_collapse is True

    def test_oos_collapse_low_sample(self):
        per_q = [
            ("2024-Q1", _mkm("2024-Q1", 0.5, trades=30)),
            ("2024-Q2", _mkm("2024-Q2", 0.4, trades=5)),  # low sample
        ]
        agg = aggregate(per_q, oos_quarter="2024-Q2")
        assert agg.oos_collapse is True

    def test_per_quarter_blobs_serialised(self):
        per_q = [("2024-Q1", _mkm("2024-Q1", 0.5))]
        agg = aggregate(per_q)
        assert agg.per_quarter[0]["quarter"] == "2024-Q1"
        # __-prefixed keys dropped from per_quarter blob.
        assert "__candidate_id__" not in agg.per_quarter[0]


class TestWalkForwardIO:
    def test_round_trip(self, tmp_path):
        agg = aggregate([("2024-Q1", _mkm("2024-Q1", 0.5))])
        path = tmp_path / "wf.json"
        save_walk_forward(agg, path)
        loaded = load_walk_forward(path)
        assert loaded.candidate_id == agg.candidate_id
        assert loaded.quarters == agg.quarters


class TestWalkForwardOrchestration:
    def test_calls_run_candidate_per_quarter(self, tmp_path):
        calls: list[str] = []

        def fake_run(*args, **kwargs):
            calls.append(kwargs.get("quarter"))
            run_dir = kwargs["run_dir"]
            run_dir.mkdir(parents=True, exist_ok=True)
            # Write a minimal metrics.json so aggregate() can parse it.
            metrics = _mkm(kwargs.get("quarter") or "?", sharpe=0.5)
            (run_dir / "metrics.json").write_text(json.dumps({
                "__aggregate__": {"experimental": metrics},
                "__meta__": {"fitness": {"experimental": 1.0}},
            }))
            return CandidateResult(
                candidate_id="c1", params_sha="abc", cluster="C1",
                gen=1, decision="accepted", metrics=metrics,
                fitness=1.0, run_dir=str(run_dir),
            )

        with mock.patch("app.loop.walk_forward.run_candidate",
                        side_effect=fake_run):
            agg = walk_forward(
                candidate_id="c1", tuning=TUNING,
                symbol_set="BTCUSD",
                quarters=["2024-Q1", "2024-Q2", "2024-Q3"],
                state_root=tmp_path,
            )

        assert sorted(calls) == ["2024-Q1", "2024-Q2", "2024-Q3"]
        assert len(agg.per_quarter) == 3
        # OOS = last quarter = 2024-Q3.
        assert agg.oos_quarter == "2024-Q3"
        assert agg.oos_collapse is False

    def test_skips_errored_quarters(self, tmp_path):
        def fake_run(*args, **kwargs):
            run_dir = kwargs["run_dir"]
            run_dir.mkdir(parents=True, exist_ok=True)
            if kwargs.get("quarter") == "2024-Q2":
                return CandidateResult(
                    candidate_id="c1", params_sha="abc", cluster="C1",
                    gen=1, decision="error", error="boom",
                    run_dir=str(run_dir),
                )
            (run_dir / "metrics.json").write_text(json.dumps({
                "__aggregate__": {"experimental": _mkm("?", 0.5)},
                "__meta__": {"fitness": {"experimental": 1.0}},
            }))
            return CandidateResult(
                candidate_id="c1", params_sha="abc", cluster="C1",
                gen=1, decision="accepted", metrics=_mkm("?", 0.5),
                fitness=1.0, run_dir=str(run_dir),
            )

        with mock.patch("app.loop.walk_forward.run_candidate",
                        side_effect=fake_run):
            agg = walk_forward(
                candidate_id="c1", tuning=TUNING, symbol_set="BTCUSD",
                quarters=["2024-Q1", "2024-Q2", "2024-Q3"],
                state_root=tmp_path,
            )
        # Q2 errored ⇒ only Q1 and Q3 in per_quarter.
        assert len(agg.per_quarter) == 2


# --- regime_buckets.py -------------------------------------------------------


class TestAggregateRegimes:
    def test_empty_inputs(self):
        agg = aggregate_regimes([])
        assert agg.worst_regime_sharpe == 0.0
        assert not agg.skewed

    def test_balanced_distributions(self):
        blob = {
            "bull": {"n": 10, "sharpe": 0.5},
            "bear": {"n": 8, "sharpe": 0.2},
            "range": {"n": 12, "sharpe": 0.4},
        }
        agg = aggregate_regimes([blob])
        assert agg.worst_regime_sharpe == pytest.approx(0.2)
        assert agg.worst_regime_label == "bear"
        assert not agg.skewed
        assert agg.dispersion > 0.0

    def test_skewed_flag(self):
        blob = {
            "bull": {"n": 95, "sharpe": 0.5},
            "bear": {"n": 5, "sharpe": 0.0},
        }
        agg = aggregate_regimes([blob])
        assert agg.skewed is True

    def test_combines_across_runs(self):
        b1 = {"bull": {"n": 10, "sharpe": 0.4}, "bear": {"n": 5, "sharpe": 0.2}}
        b2 = {"bull": {"n": 8, "sharpe": 0.6}, "bear": {"n": 6, "sharpe": 0.4}}
        agg = aggregate_regimes([b1, b2])
        # bull: n=18, sharpe_mean=(0.4+0.6)/2=0.5
        # bear: n=11, sharpe_mean=(0.2+0.4)/2=0.3
        assert agg.regimes["bull"]["n"] == 18
        assert agg.regimes["bull"]["sharpe_mean"] == pytest.approx(0.5)
        assert agg.regimes["bear"]["n"] == 11
        assert agg.regimes["bear"]["sharpe_mean"] == pytest.approx(0.3)
        assert agg.worst_regime_label == "bear"

    def test_low_sample_drops_sharpe(self):
        # n < 3 ⇒ don't count this regime's sharpe toward worst.
        blob = {
            "bull": {"n": 1, "sharpe": -10.0},
            "bear": {"n": 10, "sharpe": 0.5},
        }
        agg = aggregate_regimes([blob])
        assert agg.worst_regime_label == "bear"
        assert agg.worst_regime_sharpe == pytest.approx(0.5)


# --- oos_validator.py --------------------------------------------------------


class TestOOSValidate:
    def test_consistent_passes(self):
        in_sample = [{"sharpe": 0.5}, {"sharpe": 0.6}, {"sharpe": 0.4}]
        oos = {"sharpe": 0.55, "trades_count": 30}
        v = oos_validate(in_sample, oos)
        assert v.passed is True
        # Robustness = oos_sharpe / in_sample_mean, clipped to [0, 1].
        # in_sample_mean = 0.5, oos = 0.55 → 1.1 clipped to 1.0.
        assert v.robustness == pytest.approx(1.0)
        assert "consistent" in v.reasons[0]

    def test_low_trades_fails(self):
        in_sample = [{"sharpe": 0.5}]
        oos = {"sharpe": 0.6, "trades_count": 5}
        v = oos_validate(in_sample, oos)
        assert v.passed is False
        assert any("trade count" in r for r in v.reasons)

    def test_negative_sharpe_fails(self):
        in_sample = [{"sharpe": 0.5}]
        oos = {"sharpe": -0.3, "trades_count": 30}
        v = oos_validate(in_sample, oos)
        assert v.passed is False
        assert any("floor" in r for r in v.reasons)

    def test_drop_in_sample_fails(self):
        # In-sample mean = 1.0, OOS = 0.3 → 70% drop > 50% tolerance.
        in_sample = [{"sharpe": 1.0}]
        oos = {"sharpe": 0.3, "trades_count": 30}
        v = oos_validate(in_sample, oos)
        assert v.passed is False
        assert any("dropped" in r for r in v.reasons)

    def test_none_oos_sharpe_fails(self):
        in_sample = [{"sharpe": 0.5}]
        oos = {"sharpe": None, "trades_count": 30}
        v = oos_validate(in_sample, oos)
        assert v.passed is False
        assert any("None" in r for r in v.reasons)

    def test_robustness_clipped(self):
        # OOS > in-sample ⇒ robustness capped at 1.0.
        in_sample = [{"sharpe": 0.3}]
        oos = {"sharpe": 0.9, "trades_count": 30}
        v = oos_validate(in_sample, oos)
        assert v.robustness == 1.0

    def test_robustness_zero_when_oos_negative(self):
        in_sample = [{"sharpe": 0.5}]
        oos = {"sharpe": -0.1, "trades_count": 30}
        v = oos_validate(in_sample, oos)
        assert v.robustness == 0.0

    def test_to_dict_serialisable(self):
        in_sample = [{"sharpe": 0.5}]
        oos = {"sharpe": 0.5, "trades_count": 30}
        v = oos_validate(in_sample, oos)
        d = v.to_dict()
        # round-trip through json
        s = json.dumps(d)
        assert "passed" in s