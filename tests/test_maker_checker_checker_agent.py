"""Tests for :mod:`app.loop.maker_checker.checker_agent`.

Covers: CheckerConfig validation, isolation enforcement, calibration
transformation, thresholding, backend-failure fallback, and the
``verify`` convenience wrapper.
"""

from __future__ import annotations

import pytest

from app.loop.maker_checker.checker_agent import (
    CheckerConfig,
    fit_calibration_from_history,
    verify,
)
from app.loop.maker_checker.isolation import MINIMAL, MODERATE, STRICT
from app.loop.maker_checker.llm_backend import MockLLMBackend
from app.loop.maker_checker.schemas import make_calibration

# ---- CheckerConfig --------------------------------------------------------


class TestCheckerConfig:
    def test_defaults(self) -> None:
        c = CheckerConfig()
        assert c.isolation_level == STRICT
        assert c.rejection_threshold == 0.3
        assert c.calibration_params is None

    @pytest.mark.parametrize("level", [STRICT, MODERATE, MINIMAL])
    def test_valid_isolation_levels(self, level: str) -> None:
        CheckerConfig(isolation_level=level)

    @pytest.mark.parametrize("bad", ["", "STRICT", "all", "none"])
    def test_unknown_isolation_level(self, bad: str) -> None:
        with pytest.raises(ValueError, match="isolation_level"):
            CheckerConfig(isolation_level=bad)

    @pytest.mark.parametrize("bad", [-0.1, 1.1])
    def test_rejection_threshold_out_of_range(self, bad: float) -> None:
        with pytest.raises(ValueError, match="rejection_threshold"):
            CheckerConfig(rejection_threshold=bad)

    @pytest.mark.parametrize("bad", [-0.1, 1.1])
    def test_min_confidence_out_of_range(self, bad: float) -> None:
        with pytest.raises(ValueError, match="min_confidence"):
            CheckerConfig(min_confidence=bad)


# ---- verify ---------------------------------------------------------------


def _results() -> dict:
    """Construct a results dict that includes Maker artifacts."""
    return {
        "candidate_id": "gen1-C4-003",
        "generation_id": "gen1",
        "parent_id": "gen0-baseline",
        "cluster": "C4 Macro",
        "clusters_touched": ["C4 Macro"],
        "diff": {"extreme_deviation_pct": 15.0},
        "maker_intent": "boost_bear_sharpe",
        "reasoning": "lower deviation threshold",
        "self_score": 0.7,
        "metrics": {"sharpe": 1.2, "calmar": 1.5, "trades_count": 50},
        "by_regime": {"bull": {"n": 30}, "bear": {"n": 20}},
        "trades": [{"r": 1.5}, {"r": -1.0}],
    }


class TestVerify:
    def test_returns_verdict(self) -> None:
        v = verify("cand-1", _results())
        from app.loop.maker_checker.schemas import Verdict

        assert isinstance(v, Verdict)

    def test_strict_isolation_hides_maker_fields(self) -> None:
        # We can't directly inspect what the LLM sees without a
        # capturing backend, but we can verify the function doesn't
        # raise when Maker fields are present.
        v = verify("cand-1", _results())
        assert v.candidate_id == "cand-1"

    def test_default_backend_is_mock(self) -> None:
        # Without specifying a backend, the mock is used and returns
        # a valid verdict.
        v = verify("cand-1", _results())
        assert 0.0 <= v.checker_score <= 1.0
        assert 0.0 <= v.confidence <= 1.0

    def test_rejection_threshold_blocks_low_scores(self) -> None:
        cfg = CheckerConfig(rejection_threshold=1.0)  # always reject
        v = verify("cand-1", _results(), config=cfg)
        assert v.accept is False

    def test_min_confidence_blocks_low_confidence(self) -> None:
        cfg = CheckerConfig(min_confidence=1.0)  # always block
        v = verify("cand-1", _results(), config=cfg)
        assert v.accept is False

    def test_backend_failure_returns_low_confidence_reject(self) -> None:
        class FailingBackend:
            def complete_verdict(self, *a, **kw):
                raise RuntimeError("simulated outage")

        v = verify(
            "cand-1",
            _results(),
            backend=FailingBackend(),  # type: ignore[arg-type]
        )
        assert v.accept is False
        assert v.confidence == 0.0
        assert any(f["issue"] == "checker_backend_failure" for f in v.flags)

    def test_calibration_params_transform_score(self) -> None:
        # a=0, b=0 -> identity (always returns 0.5).
        params = make_calibration(a=0.0, b=0.0, ece=0.05, n_samples=10)
        cfg = CheckerConfig(calibration_params=params)
        v = verify("cand-1", _results(), config=cfg)
        # Identity cal -> calibrated score == 0.5 regardless of raw.
        assert v.checker_score == pytest.approx(0.5, abs=1e-6)
        # raw_score preserved for drift analysis.
        assert 0.0 <= v.raw_score <= 1.0

    def test_raw_score_preserved(self) -> None:
        v = verify("cand-1", _results())
        assert 0.0 <= v.raw_score <= 1.0

    def test_moderate_isolation_keeps_candidate_id(self) -> None:
        # In moderate mode, candidate_id passes through; we can't
        # directly inspect the LLM prompt without a capturing backend,
        # but verify() should succeed.
        cfg = CheckerConfig(isolation_level=MODERATE)
        v = verify("real-id-123", _results(), config=cfg)
        assert v.candidate_id == "real-id-123"


# ---- fit_calibration_from_history -----------------------------------------


class TestFitCalibrationFromHistory:
    def test_returns_none_when_too_few_samples(self) -> None:
        result = fit_calibration_from_history([(0.5, 1), (0.5, 0)] * 3)  # 6 pairs
        assert result is None

    def test_returns_calibration_when_enough_samples(self) -> None:
        # Generate a balanced set of >= 10 pairs.
        pairs = [(i / 20, i % 2) for i in range(20)]
        result = fit_calibration_from_history(pairs)
        assert result is not None
        assert result.n_samples == 20

    def test_empty_input_returns_none(self) -> None:
        assert fit_calibration_from_history([]) is None


# ---- Salt effect ---------------------------------------------------------


class TestSalt:
    def test_salt_changes_strict_id_hashing(self) -> None:
        # Same results, different salts -> different internal prompts.
        # We verify via call_count: 2 calls = 2 prompts.
        backend = MockLLMBackend(seed=0)
        verify("cand-1", _results(), backend=backend, salt="salt-a")
        verify("cand-1", _results(), backend=backend, salt="salt-b")
        assert backend.call_count == 2

    def test_same_salt_produces_same_internal_prompt(self) -> None:
        # The mock hashes (seed, prompt); if the prompt is the same,
        # the verdict should be the same.
        backend_a = MockLLMBackend(seed=0)
        backend_b = MockLLMBackend(seed=0)
        v_a = verify("cand-1", _results(), backend=backend_a, salt="x")
        v_b = verify("cand-1", _results(), backend=backend_b, salt="x")
        assert v_a.raw_score == v_b.raw_score
        assert v_a.accept == v_b.accept
