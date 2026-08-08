"""Tests for app.loop.mutation + app.loop.sensitivity + app.loop.search.

These tests exercise the M3 modules WITHOUT invoking the real backtest
harness. The sensitivity scan uses a synthetic fitness function
(:func:`app.loop.sensitivity.mock_fitness_noisy`) so we can validate the
σ calibration logic in milliseconds.
"""

from __future__ import annotations

import json
import random

import pytest

from app.config.tuning import TUNING, TuningConstants, to_dict
from app.loop.mutation import (
    DEFAULT_CLUSTER_MAP,
    all_clusters,
    cluster_fields,
    mutate_all_clusters,
    mutate_cluster,
    mutate_field,
    random_child,
)
from app.loop.search import (
    GenerationConfig,
    GenerationResult,
    check_safety,
    make_child_candidates,
    run_generation,
)
from app.loop.sensitivity import (
    FieldSensitivity,
    SensitivityReport,
    load_report,
    mock_fitness_noisy,
    save_report,
    sensitivity_scan,
)

# --- mutation.py --------------------------------------------------------------


class TestMutateField:
    def test_abs_small_within_bounds(self):
        rng = random.Random(0)
        t = mutate_field(
            "atr_prz_sweep", "abs_small", {"min": 0.05, "max": 1.0}, TUNING, rng, sigma_scale=10.0
        )  # huge σ ⇒ hits bounds
        v = t.atr_prz_sweep
        assert 0.05 <= v <= 1.0

    def test_int_window_integer(self):
        rng = random.Random(0)
        t = mutate_field("atr_window", "int_window", {"min": 5, "max": 50}, TUNING, rng)
        assert isinstance(t.atr_window, int)
        assert 5 <= t.atr_window <= 50

    def test_dict_per_key_all_keys_perturbed(self):
        rng = random.Random(0)
        t = mutate_field("confluence_weights", "dict_per_key", {"per_key": 0.10}, TUNING, rng, sigma_scale=1.0)
        assert set(t.confluence_weights.keys()) == set(TUNING.confluence_weights.keys())

    def test_dict_per_key_per_key_bounds_enforced(self):
        """``keys_bounds`` overrides the global min/max for named keys.

        Used by ``atr_stop_buffer`` so the standard key cannot regress above
        0.5 ATR (the deliberate tightening; see stop-loss-expert-tuning plan).
        """
        rng = random.Random(0)
        kwargs = {
            "per_key": 0.20,
            "keys_bounds": {
                "conservative": (0.5, 2.0),
                "standard": (0.2, 0.5),
                "aggressive": (0.1, 0.4),
            },
        }
        # Run many trials; every perturbed standard value must stay in [0.2, 0.5].
        for seed in range(50):
            rng_i = random.Random(seed)
            t = mutate_field("atr_stop_buffer", "dict_per_key", kwargs, TUNING, rng_i, sigma_scale=10.0)
            assert 0.5 <= t.atr_stop_buffer["conservative"] <= 2.0, t.atr_stop_buffer
            assert 0.2 <= t.atr_stop_buffer["standard"] <= 0.5, t.atr_stop_buffer
            assert 0.1 <= t.atr_stop_buffer["aggressive"] <= 0.4, t.atr_stop_buffer

    def test_dict_per_key_unchanged_keys_use_global_bounds(self):
        """Keys not listed in ``keys_bounds`` fall back to the global min/max."""
        rng = random.Random(0)
        kwargs = {
            "per_key": 0.20,
            "min": 0.0,
            "max": 5.0,
            "keys_bounds": {"standard": (0.2, 0.5)},
        }
        t = mutate_field("atr_stop_buffer", "dict_per_key", kwargs, TUNING, rng, sigma_scale=10.0)
        # standard was bounded; conservative/aggressive follow global max=5.
        assert 0.2 <= t.atr_stop_buffer["standard"] <= 0.5
        assert t.atr_stop_buffer["conservative"] <= 5.0
        assert t.atr_stop_buffer["aggressive"] <= 5.0

    def test_unknown_kind_raises(self):
        rng = random.Random(0)
        with pytest.raises(ValueError):
            mutate_field("a_grade_min", "garbage_kind", {}, TUNING, rng)

    def test_replaces_only_one_field(self):
        rng = random.Random(0)
        before = to_dict(TUNING)
        t = mutate_field("a_grade_min", "int_threshold", {"min": 50, "max": 95}, TUNING, rng)
        after = to_dict(t)
        diffs = [k for k in before if before[k] != after[k]]
        assert diffs == ["a_grade_min"]


class TestMutateCluster:
    def test_mutates_one_field_by_default(self):
        rng = random.Random(0)
        before = to_dict(TUNING)
        t = mutate_cluster(TUNING, "C1 Geometry", rng=rng)
        diffs = [k for k in to_dict(t) if to_dict(t)[k] != before[k]]
        assert len(diffs) == 1

    def test_unknown_cluster_returns_unchanged(self):
        t = mutate_cluster(TUNING, "C9 Unknown", rng=random.Random(0))
        assert to_dict(t) == to_dict(TUNING)

    def test_n_mutations_respected(self):
        rng = random.Random(0)
        before = to_dict(TUNING)
        t = mutate_cluster(TUNING, "C3 Confluence", rng=rng, n_mutations=3)
        diffs = [k for k in to_dict(t) if to_dict(t)[k] != before[k]]
        assert len(diffs) == 3

    def test_n_mutations_capped_by_cluster_size(self):
        rng = random.Random(0)
        before = to_dict(TUNING)
        t = mutate_cluster(TUNING, "C1 Geometry", rng=rng, n_mutations=999)
        # C1 has 12 fields; can't exceed that.
        diffs = [k for k in to_dict(t) if to_dict(t)[k] != before[k]]
        assert 1 <= len(diffs) <= 12


class TestMutateAllClusters:
    def test_touches_every_cluster(self):
        rng = random.Random(0)
        before = to_dict(TUNING)
        t = mutate_all_clusters(TUNING, rng=rng)
        diffs = [k for k in to_dict(t) if to_dict(t)[k] != before[k]]
        # 5 clusters, at least 5 fields should have moved.
        assert len(diffs) >= 5


class TestRandomChild:
    def test_returns_new_instance(self):
        c = random_child(TUNING, seed=1)
        assert isinstance(c, TuningConstants)
        assert c is not TUNING  # always a new frozen-replaced copy

    def test_default_parent(self):
        c = random_child(seed=1)
        # Must mutate exactly one field of TUNING.
        diffs = [k for k in to_dict(c) if to_dict(c)[k] != to_dict(TUNING)[k]]
        assert len(diffs) == 1

    def test_seed_reproducibility(self):
        a = random_child(TUNING, seed=42)
        b = random_child(TUNING, seed=42)
        assert to_dict(a) == to_dict(b)


class TestClusterUtils:
    def test_all_clusters_is_five(self):
        assert set(all_clusters()) == {
            "C1 Geometry",
            "C2 Discipline",
            "C3 Confluence",
            "C4 Macro",
            "C5 Windows",
        }

    def test_cluster_fields_returns_strings(self):
        for c in all_clusters():
            fields = cluster_fields(c)
            assert fields
            assert all(isinstance(f, str) for f in fields)


# --- sensitivity.py ----------------------------------------------------------


class TestSensitivityScan:
    def test_returns_one_entry_per_field(self):
        report = sensitivity_scan(fitness_fn=mock_fitness_noisy, seed=1)
        n_fields = sum(len(m) for m in DEFAULT_CLUSTER_MAP.values())
        assert len(report.fields) == n_fields

    def test_recommends_smaller_sigma_for_steep_fields(self):
        # A "steeper" mock fitness — gradient much larger for one field.
        def steep(t):
            return (t.a_grade_min - 70) * 1.0  # big slope on a_grade_min

        report = sensitivity_scan(fitness_fn=steep, seed=1)
        a_field = next(f for f in report.fields if f.field == "a_grade_min")
        # Pick any field in a different cluster — it has zero gradient here.
        flat_field = next(f for f in report.fields if f.cluster == "C5 Windows")
        assert a_field.gradient_abs > flat_field.gradient_abs
        assert a_field.recommended_sigma_scale <= flat_field.recommended_sigma_scale

    def test_skips_fields(self):
        report = sensitivity_scan(
            fitness_fn=mock_fitness_noisy,
            seed=1,
            fields_to_skip=["a_grade_min"],
        )
        assert all(f.field != "a_grade_min" for f in report.fields)

    def test_sigma_scale_clamped(self):
        # Constant fitness ⇒ infinite gradient ratio ⇒ scale clamped.
        def const(_t):
            return 1.0

        report = sensitivity_scan(fitness_fn=const, seed=1)
        for f in report.fields:
            assert 0.25 <= f.recommended_sigma_scale <= 4.0


class TestSensitivityReportIO:
    def test_round_trip(self, tmp_path):
        report = sensitivity_scan(fitness_fn=mock_fitness_noisy, seed=1)
        path = tmp_path / "sensitivity.json"
        save_report(report, path)
        loaded = load_report(path)
        assert len(loaded.fields) == len(report.fields)
        assert loaded.default_sigma_scale == report.default_sigma_scale


class TestSensitivityReportScaleFor:
    def test_returns_field_scale_when_known(self):
        r = SensitivityReport(
            fields=[
                FieldSensitivity(
                    field="x",
                    cluster="C",
                    kind="abs_small",
                    baseline_value=0,
                    plus_delta=0.5,
                    minus_delta=0.5,
                    gradient_abs=0.5,
                    recommended_sigma_scale=2.0,
                ),
            ]
        )
        assert r.scale_for("x") == 2.0

    def test_falls_back_to_default(self):
        r = SensitivityReport(fields=[], default_sigma_scale=1.5)
        assert r.scale_for("missing") == 1.5


# --- search.py ---------------------------------------------------------------


class TestCheckSafety:
    def test_all_pass_default(self):
        cfg = GenerationConfig(
            gen=1,
            parent_sha="abc",
            parent=TUNING,
            cluster="C1 Geometry",
        )
        checks = check_safety(cfg)
        assert all(c.ok for c in checks)
        assert {c.name for c in checks} >= {
            "diff_size",
            "timeout_floor",
            "weekly_budget",
            "cluster_exists",
        }
        # Defaults must match docs/loop-state/loop-budget.md
        assert cfg.weekly_budget_usd == 25.0
        assert cfg.dollars_per_cpu_second == 0.0001

    def test_over_budget_fails(self):
        cfg = GenerationConfig(
            gen=1,
            parent_sha="abc",
            parent=TUNING,
            cluster="C1 Geometry",
            weekly_budget_usd=25.0,
            lambda_=10,
        )
        checks = check_safety(cfg, weekly_spend_usd=24.99)
        budget = next(c for c in checks if c.name == "weekly_budget")
        assert not budget.ok

    def test_disable_loop_budget_env(self, monkeypatch):
        from app.loop.search import budget_defaults

        monkeypatch.setenv("DISABLE_LOOP_BUDGET", "1")
        assert budget_defaults() == (0.0, 0.0)
        monkeypatch.delenv("DISABLE_LOOP_BUDGET", raising=False)
        assert budget_defaults() == (25.0, 0.0001)

    def test_too_many_mutations_fails(self):
        cfg = GenerationConfig(
            gen=1,
            parent_sha="abc",
            parent=TUNING,
            cluster="C1 Geometry",
            n_mutations=10,
        )
        checks = check_safety(cfg)
        diff_check = next(c for c in checks if c.name == "diff_size")
        assert not diff_check.ok

    def test_low_timeout_fails(self):
        cfg = GenerationConfig(
            gen=1,
            parent_sha="abc",
            parent=TUNING,
            cluster="C1 Geometry",
            timeout_seconds=10,
        )
        checks = check_safety(cfg)
        to_check = next(c for c in checks if c.name == "timeout_floor")
        assert not to_check.ok

    def test_unknown_cluster_fails(self):
        cfg = GenerationConfig(
            gen=1,
            parent_sha="abc",
            parent=TUNING,
            cluster="C9 Unknown",
        )
        checks = check_safety(cfg)
        cl_check = next(c for c in checks if c.name == "cluster_exists")
        assert not cl_check.ok


class TestMakeChildCandidates:
    def test_lambda_candidates(self):
        children = make_child_candidates(
            TUNING,
            "C1 Geometry",
            lambda_=5,
            sigma_scale=1.0,
            n_mutations=1,
            gen=1,
        )
        assert len(children) == 5
        assert all("candidate_id" in c and "tuning" in c for c in children)

    def test_candidate_ids_are_unique(self):
        children = make_child_candidates(
            TUNING,
            "C3 Confluence",
            lambda_=10,
            sigma_scale=1.0,
            n_mutations=1,
            gen=2,
        )
        ids = [c["candidate_id"] for c in children]
        assert len(set(ids)) == 10

    def test_with_sensitivity_uses_per_field_scale(self):
        report = sensitivity_scan(fitness_fn=mock_fitness_noisy, seed=1)
        children = make_child_candidates(
            TUNING,
            "C3 Confluence",
            lambda_=4,
            sigma_scale=1.0,
            n_mutations=2,
            gen=1,
            sensitivity=report,
            seed=0,
        )
        assert len(children) == 4

    def test_seed_reproducible(self):
        a = make_child_candidates(
            TUNING,
            "C2 Discipline",
            lambda_=3,
            sigma_scale=1.0,
            n_mutations=2,
            gen=1,
            seed=7,
        )
        b = make_child_candidates(
            TUNING,
            "C2 Discipline",
            lambda_=3,
            sigma_scale=1.0,
            n_mutations=2,
            gen=1,
            seed=7,
        )
        assert [c["tuning"] for c in a] == [c["tuning"] for c in b]


class TestRunGeneration:
    def test_skips_on_failed_safety(self, tmp_path):
        cfg = GenerationConfig(
            gen=1,
            parent_sha="abc",
            parent=TUNING,
            cluster="C9 Unknown",
            n_mutations=10,
            timeout_seconds=10,
        )
        res = run_generation(cfg, state_root=tmp_path)
        assert res.skipped is True
        assert res.candidates == []
        assert "cluster_exists" in res.skip_reason

    def test_writes_candidates_file(self, tmp_path):
        cfg = GenerationConfig(
            gen=3,
            parent_sha="abc",
            parent=TUNING,
            cluster="C1 Geometry",
            lambda_=4,
        )
        res = run_generation(cfg, state_root=tmp_path, quarter="2024-Q4")
        assert res.skipped is False
        cand = json.loads((tmp_path / "next_generation.json").read_text())
        assert cand["gen"] == 3
        assert cand["cluster"] == "C1 Geometry"
        assert cand["quarter"] == "2024-Q4"
        assert len(cand["candidates"]) == 4

    def test_respects_sensitivity_report(self, tmp_path):
        report = sensitivity_scan(fitness_fn=mock_fitness_noisy, seed=1)
        cfg = GenerationConfig(
            gen=1,
            parent_sha="abc",
            parent=TUNING,
            cluster="C3 Confluence",
            lambda_=2,
            n_mutations=1,
        )
        res = run_generation(cfg, state_root=tmp_path, sensitivity=report)
        assert len(res.candidates) == 2

    def test_returns_generation_result_shape(self, tmp_path):
        cfg = GenerationConfig(
            gen=1,
            parent_sha="abc",
            parent=TUNING,
            cluster="C5 Windows",
        )
        res = run_generation(cfg, state_root=tmp_path)
        assert isinstance(res, GenerationResult)
        assert res.elapsed_seconds >= 0
        assert res.parent_sha == "abc"
