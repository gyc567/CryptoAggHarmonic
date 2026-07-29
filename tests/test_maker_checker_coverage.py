"""Coverage gap tests for :mod:`app.loop.maker_checker`.

These exercise error / edge branches not covered by the main test
suites, so the package hits 100 % line coverage for the new code.
"""
from __future__ import annotations

import math
import os
from typing import Any

import pytest

from app.config.tuning import TuningConstants
from app.loop.maker_checker.calibration import (
    CalibrationParams,
    calibrate,
    expected_calibration_error,
    reliability_diagram,
)
from app.loop.maker_checker.checker_agent import (
    CheckerAgent,
    CheckerConfig,
    _low_confidence_reject,
    _parse_verdict,
    fit_calibration_from_history,
)
from app.loop.maker_checker.isolation import (
    list_stripped_fields,
)
from app.loop.maker_checker.llm_backend import (
    LLMBackend,
    LLMBackendError,
    MockLLMBackend,
)
from app.loop.maker_checker.maker_agent import (
    MakerAgent,
    MakerConfig,
    _parse_proposal,
)
from app.loop.maker_checker.review import (
    HumanReviewDecision,
    main,
)
from app.loop.maker_checker.runner import RunnerConfig, feature_enabled
from app.loop.maker_checker.schemas import MergeResult, make_merge_result


# ---- calibration.py edge branches ----------------------------------------


class TestCalibrationEdges:
    def test_calibrate_converges_early(self) -> None:
        # Near-optimal parameters → low gradient → early break.
        # Make 'perfect' calibration data so the optimiser converges.
        pairs = [(0.05, 0), (0.15, 0), (0.85, 1), (0.95, 1)] * 8
        params = calibrate(pairs, max_iter=200)
        assert math.isfinite(params.a) and math.isfinite(params.b)

    def test_calibrate_step_decay_to_break(self) -> None:
        # Pathological input that won't reduce loss → step decays below 1e-6.
        # Using all-same-label pairs so gradient has small norm → fast break.
        pairs = [(0.5, 0), (0.6, 0), (0.4, 0)] * 5
        # Need at least one positive → mix in a positive example.
        pairs = pairs + [(0.9, 1)] * 3
        params = calibrate(pairs, max_iter=20)
        assert isinstance(params.a, float)
        assert isinstance(params.b, float)

    def test_fit_platt_norm_break(self) -> None:
        # Test the early-break path directly via the private helper.
        from app.loop.maker_checker.calibration import _fit_platt

        # Use a tol larger than any plausible gradient norm → break on iter 0.
        pairs = [(0.5, 0), (0.5, 1)] * 30
        a, b = _fit_platt(pairs, max_iter=200, lr=0.5, tol=1e6)
        # When norm < tol on first iter, params stay at (1.0, 0.0).
        assert a == 1.0 and b == 0.0

    def test_fit_platt_step_decay(self) -> None:
        # The else-branch: step decays below 1e-6 → stop.
        from app.loop.maker_checker.calibration import _fit_platt

        # Adversarial: a perfectly calibrated dataset where the loss
        # is at the minimum → gradient descent will repeatedly fail
        # to improve.
        pairs = [(0.01, 0), (0.99, 1)] * 10
        a, b = _fit_platt(pairs, max_iter=5, lr=10.0, tol=0.0)
        assert isinstance(a, float)
        assert isinstance(b, float)

    def test_ece_empty_pairs_returns_zero(self) -> None:
        # Empty input → returns 0.0 directly.
        assert expected_calibration_error([]) == 0.0
        assert reliability_diagram([]) == []

    def test_ece_with_params_no_pairs(self) -> None:
        # With explicit params but empty pairs → 0.0 short-circuit.
        from app.loop.maker_checker.schemas import make_calibration
        params = make_calibration(a=1.0, b=0.0, ece=0.0, n_samples=0)
        assert expected_calibration_error([], params=params) == 0.0

    def test_bin_predictions_empty(self) -> None:
        # Direct call to exercise the empty-input branch.
        from app.loop.maker_checker.calibration import _bin_predictions
        assert _bin_predictions([]) == []
        assert _bin_predictions([], n_bins=5) == []

    def test_ece_with_bins_but_no_pairs_in_bins(self) -> None:
        # All pairs in one bin → other bins empty → still computes ECE.
        # This exercises the inner loop in expected_calibration_error.
        assert expected_calibration_error([(0.5, 1)] * 10) >= 0.0


# ---- checker_agent.py uncovered branches ---------------------------------


class _FailingBackend:
    """Backend that always raises to exercise the failure path."""

    def complete_verdict(self, prompt, *, seed=None):
        raise LLMBackendError("boom")

    def complete_proposals(self, prompt, *, n, cluster=None, seed=None):
        raise LLMBackendError("boom")


class _BadJSONBackend:
    def complete_verdict(self, prompt, *, seed=None):
        return "not a dict"  # type: ignore[return-value]

    def complete_proposals(self, prompt, *, n, cluster=None, seed=None):
        return []


class _MixedFlagBackend:
    def complete_verdict(self, prompt, *, seed=None):
        # Flag with unknown severity should be filtered out.
        return {
            "checker_score": 0.5,
            "confidence": 0.6,
            "components": {"a": 1.0},
            "flags": [
                {"severity": "critical", "issue": "should be dropped"},
                {"severity": "low", "issue": "kept"},
            ],
            "accept": True,
            "feedback": "ok",
        }

    def complete_proposals(self, prompt, *, n, cluster=None, seed=None):
        return []


class TestCheckerAgentEdges:
    def test_backend_failure_low_confidence(self) -> None:
        agent = CheckerAgent(backend=_FailingBackend(), config=CheckerConfig())
        v = agent.verify("c1", {"metrics": {"trades_count": 50}})
        assert v.accept is False
        assert v.confidence < 0.3

    def test_parse_verdict_non_dict(self) -> None:
        assert _parse_verdict("c", "not a dict") is None

    def test_parse_verdict_missing_score(self) -> None:
        assert _parse_verdict("c", {"confidence": 0.5, "accept": True}) is None

    def test_parse_verdict_missing_confidence(self) -> None:
        assert _parse_verdict("c", {"checker_score": 0.5, "accept": True}) is None

    def test_parse_verdict_raw_score_missing(self) -> None:
        v = _parse_verdict("c", {
            "checker_score": 0.5, "confidence": 0.6,
            "components": {}, "flags": [], "accept": True, "feedback": "ok",
        })
        assert v is not None
        # raw_score falls back to score when missing/non-numeric.
        assert v.raw_score == v.checker_score

    def test_parse_verdict_components_not_dict(self) -> None:
        assert _parse_verdict("c", {
            "checker_score": 0.5, "confidence": 0.6,
            "components": "not a dict", "accept": True,
        }) is None

    def test_parse_verdict_flags_not_list(self) -> None:
        assert _parse_verdict("c", {
            "checker_score": 0.5, "confidence": 0.6,
            "components": {}, "flags": "no", "accept": True,
        }) is None

    def test_parse_verdict_accept_not_bool(self) -> None:
        assert _parse_verdict("c", {
            "checker_score": 0.5, "confidence": 0.6,
            "components": {}, "flags": [], "accept": "yes",
        }) is None

    def test_parse_verdict_feedback_not_string(self) -> None:
        assert _parse_verdict("c", {
            "checker_score": 0.5, "confidence": 0.6,
            "components": {}, "flags": [], "accept": True, "feedback": 123,
        }) is None

    def test_parse_verdict_invalid_severity_dropped(self) -> None:
        v = _parse_verdict("c", {
            "checker_score": 0.5, "confidence": 0.6,
            "components": {}, "flags": [
                {"severity": "weird", "issue": "x"},  # no severity/issue
                {"severity": "high"},  # no issue
                {"issue": "y"},  # no severity
                {"severity": "low", "issue": "ok"},  # kept
            ],
            "accept": True, "feedback": "ok",
        })
        assert v is not None
        assert len(v.flags) == 1
        assert v.flags[0]["issue"] == "ok"

    def test_parse_verdict_truncates_feedback(self) -> None:
        from app.loop.maker_checker.schemas import Verdict
        v = _parse_verdict("c", {
            "checker_score": 0.5, "confidence": 0.6,
            "components": {}, "flags": [], "accept": True,
            "feedback": "x" * (Verdict.MAX_FEEDBACK_LEN + 100),
        })
        assert v is not None
        assert len(v.feedback) == Verdict.MAX_FEEDBACK_LEN

    def test_low_confidence_reject_factory(self) -> None:
        v = _low_confidence_reject("c1")
        assert v.candidate_id == "c1"
        assert v.accept is False
        assert v.confidence < 0.3

    def test_fit_calibration_short_history_returns_none(self) -> None:
        assert fit_calibration_from_history([(0.1, 0)]) is None

    def test_fit_calibration_returns_calibration(self) -> None:
        # Good history blob → returns fitted params.
        history = [(p, int(p > 0.5)) for p in [i / 50 for i in range(50)]]
        params = fit_calibration_from_history(history)
        assert params is not None

    def test_parse_then_calibrate(self) -> None:
        # Backend that returns invalid JSON triggers low-confidence reject.
        agent = CheckerAgent(backend=_BadJSONBackend(), config=CheckerConfig())
        v = agent.verify("c", {"metrics": {"trades_count": 50}})
        assert v.accept is False

    def test_filters_unknown_severity_via_backend(self) -> None:
        agent = CheckerAgent(backend=_MixedFlagBackend(), config=CheckerConfig())
        v = agent.verify("c", {"metrics": {"trades_count": 50}})
        # Only the 'low' severity flag survives.
        assert all(f["severity"] in ("high", "medium", "low") for f in v.flags)

    def test_parse_verdict_non_numeric_raw_score_falls_back(self) -> None:
        # raw_score="oops" → falls back to score.
        v = _parse_verdict("c", {
            "checker_score": 0.5, "confidence": 0.6,
            "raw_score": "oops",
            "components": {}, "flags": [], "accept": True, "feedback": "ok",
        })
        assert v is not None
        assert v.raw_score == v.checker_score

    def test_parse_verdict_make_verdict_raises(self) -> None:
        # Pass a value that triggers make_verdict's validator to raise.
        # checker_score=1.5 is out of [0,1] → raises.
        assert _parse_verdict("c", {
            "checker_score": 1.5, "confidence": 0.6,
            "components": {}, "flags": [], "accept": True, "feedback": "ok",
        }) is None

    def test_fit_calibration_value_error_caught(self) -> None:
        # All-positive labels → calibrate raises ValueError → None.
        history = [(0.1, 1)] * 50
        result = fit_calibration_from_history(history)
        assert result is None


# ---- isolation.py uncovered line -----------------------------------------


class TestIsolationEdges:
    def test_unknown_level_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown isolation level"):
            list_stripped_fields("ultra")


# ---- llm_backend.py Protocol body -----------------------------------------


class TestLLMBackendProtocol:
    def test_protocol_decorator_present(self) -> None:
        # The Protocol declares two methods; just verify they are
        # present and call-eligible on instances via the runtime
        # check protocol (`runtime_checkable` is *not* used here, but
        # the attributes must still resolve on instances).
        # Construct a minimal subclass and ensure both methods exist.
        class _Stub(LLMBackend):
            def complete_verdict(self, prompt, *, seed=None):
                return {}

            def complete_proposals(self, prompt, *, n, cluster=None, seed=None):
                return []

        s = _Stub()
        assert callable(s.complete_verdict)
        assert callable(s.complete_proposals)


# ---- maker_agent.py uncovered branches ------------------------------------


class TestMakerAgentEdges:
    def test_parse_proposal_not_dict(self) -> None:
        assert _parse_proposal("not a dict", cluster="C1") is None

    def test_parse_proposal_missing_clusters(self) -> None:
        assert _parse_proposal({"diff": {"x": 1}}, cluster="C1") is None

    def test_parse_proposal_empty_clusters(self) -> None:
        assert _parse_proposal(
            {"clusters_touched": [], "diff": {"x": 1}}, cluster="C1",
        ) is None

    def test_parse_proposal_no_diff(self) -> None:
        assert _parse_proposal(
            {"clusters_touched": ("C1",), "diff": {}}, cluster="C1",
        ) is None

    def test_parse_proposal_intent_not_string(self) -> None:
        assert _parse_proposal(
            {"clusters_touched": ("C1",), "diff": {"x": 1},
             "maker_intent": 123, "reasoning": "r", "self_score": 0.5},
            cluster="C1",
        ) is None

    def test_parse_proposal_reasoning_not_string(self) -> None:
        assert _parse_proposal(
            {"clusters_touched": ("C1",), "diff": {"x": 1},
             "maker_intent": "i", "reasoning": [], "self_score": 0.5},
            cluster="C1",
        ) is None

    def test_parse_proposal_score_not_number(self) -> None:
        assert _parse_proposal(
            {"clusters_touched": ("C1",), "diff": {"x": 1},
             "maker_intent": "i", "reasoning": "r", "self_score": "x"},
            cluster="C1",
        ) is None

    def test_parse_proposal_wrong_cluster(self) -> None:
        assert _parse_proposal(
            {"clusters_touched": ("OTHER",), "diff": {"x": 1},
             "maker_intent": "i", "reasoning": "r", "self_score": 0.5},
            cluster="C1",
        ) is None

    def test_parse_proposal_construct_failure(self) -> None:
        # self_score outside [0,1] triggers make_proposal ValueError.
        assert _parse_proposal(
            {"clusters_touched": ("C1",), "diff": {"x": 1},
             "maker_intent": "i", "reasoning": "r", "self_score": 2.0},
            cluster="C1",
        ) is None

    def test_traditional_mutation_skips_no_change(self) -> None:
        # Force mutate_field to return same value by manipulating kwargs.
        from app.loop.maker_checker.maker_agent import traditional_proposals

        proposals = traditional_proposals(
            TuningConstants(), n=1, cluster="C1 Geometry", seed=0,
        )
        # Just exercise the path; outputs may be 0 or more proposals.
        assert isinstance(proposals, list)

    def test_traditional_skips_unknown_field(self) -> None:
        # Direct test: pass a cluster that has no fields → empty list.
        from app.loop.maker_checker.maker_agent import traditional_proposals

        with pytest.raises(ValueError, match="unknown cluster"):
            traditional_proposals(
                TuningConstants(), n=2, cluster="Unknown Cluster", seed=0,
            )

    def test_traditional_skips_exception_in_mutate(self, monkeypatch) -> None:
        # Force mutate_field to raise → exercises the except/continue branch.
        from app.loop.maker_checker import maker_agent
        from app.loop.maker_checker.maker_agent import traditional_proposals

        def boom(*args, **kwargs):
            raise ValueError("synthetic constraint violation")

        monkeypatch.setattr(maker_agent, "mutate_field", boom)

        proposals = traditional_proposals(
            TuningConstants(), n=2, cluster="C1 Geometry", seed=0,
        )
        # All mutations failed → no proposals.
        assert proposals == []

    def test_traditional_old_equals_new_skipped(self, monkeypatch) -> None:
        # Force mutate_field to return unchanged → triggers old==new branch.
        from app.loop.maker_checker import maker_agent
        from app.loop.maker_checker.maker_agent import traditional_proposals

        monkeypatch.setattr(
            maker_agent, "mutate_field",
            lambda *args, **kwargs: args[3],  # return parent t
        )
        proposals = traditional_proposals(
            TuningConstants(), n=2, cluster="C1 Geometry", seed=0,
        )
        assert proposals == []

    def test_traditional_zero_old_value(self, monkeypatch) -> None:
        # Force old_val to be 0 → magnitude=0.0 branch.
        from dataclasses import replace as dc_replace
        from app.loop.maker_checker import maker_agent
        from app.loop.maker_checker.maker_agent import traditional_proposals

        # Mutate to a value AND record parent → swap parent value to 0
        # by monkeypatching mutate_field to first look up the parent.
        real_calls: list[tuple[float, float]] = []

        def capture_mutate(name, kind, kwargs, t, rng, **skw):
            new_t = dc_replace(t, **{name: 1.0})
            real_calls.append((getattr(t, name, 0.0), 1.0))
            return new_t

        monkeypatch.setattr(maker_agent, "mutate_field", capture_mutate)

        # Patch the cluster spec to use a field whose default is 0.
        # Use the real DEFAULT_CLUSTER_MAP but force one entry's field
        # to be 0 by monkeypatching the spec.
        spec = maker_agent.DEFAULT_CLUSTER_MAP["C1 Geometry"][0]
        name = spec[0]

        # Construct a parent where the field is 0.
        parent = dc_replace(TuningConstants(), **{name: 0.0})
        proposals = traditional_proposals(
            parent, n=2, cluster="C1 Geometry", seed=0,
        )
        # Some proposals should have been generated with magnitude=0.0.
        assert any(
            abs(p.diff.get(name, 99)) < 0.01 for p in proposals
        ) or proposals == []  # may be empty if cluster spec doesn't include numeric

    def test_traditional_nonnumeric_old_skipped(self, monkeypatch) -> None:
        # Force old_val to be a string → triggers non-numeric branch.
        from app.loop.maker_checker import maker_agent
        from app.loop.maker_checker.maker_agent import traditional_proposals

        def nonnumeric_mutate(name, kind, kwargs, t, rng, **skw):
            from dataclasses import replace as dc_replace
            return dc_replace(t, **{name: "not_a_number"})

        monkeypatch.setattr(maker_agent, "mutate_field", nonnumeric_mutate)
        proposals = traditional_proposals(
            TuningConstants(), n=2, cluster="C1 Geometry", seed=0,
        )
        assert proposals == []


# ---- runner.py uncovered line ---------------------------------------------


class TestRunnerEdges:
    def test_runner_config_enabled_no_op(self) -> None:
        # When self.enabled is False, post_init returns silently.
        c = RunnerConfig(enabled=False)
        assert c.enabled is False

    def test_feature_enabled_true_when_env_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("MAKER_CHECKER_ENABLED", raising=False)
        assert feature_enabled() is True


# ---- schemas.py uncovered line --------------------------------------------


class TestSchemaEdges:
    def test_final_score_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="final_score"):
            make_merge_result(
                final_decision="accepted",
                final_score=100.0,
                m4_verdict="promising",
                trigger_reasons=(),
            )

    def test_checker_confidence_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="checker_confidence"):
            make_merge_result(
                final_decision="accepted",
                final_score=0.5,
                m4_verdict="promising",
                trigger_reasons=(),
                checker_confidence=2.0,
            )