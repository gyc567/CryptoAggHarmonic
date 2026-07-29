"""Tests for :mod:`app.loop.maker_checker.schemas`.

Covers: validation rules, convenience constructors, edge cases, the
5-D Pareto back-compat invariant (``None`` -> ``-inf``).
"""
from __future__ import annotations

import pytest

from app.loop.maker_checker.schemas import (
    CalibrationParams,
    MakerSelfScore,
    MergeResult,
    Proposal,
    Verdict,
    make_calibration,
    make_merge_result,
    make_proposal,
    make_verdict,
)


# ---- MakerSelfScore -------------------------------------------------------


class TestMakerSelfScore:
    def test_valid_score_passes(self) -> None:
        s = MakerSelfScore(self_score=0.5)
        assert s.self_score == 0.5

    def test_zero_and_one_are_valid(self) -> None:
        MakerSelfScore(self_score=0.0)
        MakerSelfScore(self_score=1.0)

    @pytest.mark.parametrize("bad", [-0.01, 1.01, -1.0, 2.0])
    def test_out_of_range_raises(self, bad: float) -> None:
        with pytest.raises(ValueError, match="must be in"):
            MakerSelfScore(self_score=bad)

    def test_frozen(self) -> None:
        s = MakerSelfScore(self_score=0.5)
        with pytest.raises(Exception):
            s.self_score = 0.9  # type: ignore[misc]


# ---- Proposal -------------------------------------------------------------


class TestProposal:
    def test_valid_proposal(self) -> None:
        p = make_proposal(
            clusters_touched=("C4 Macro",),
            diff={"extreme_deviation_pct": 15.0},
            maker_intent="boost_bear_sharpe",
            reasoning="lower deviation threshold to catch more setups",
            self_score=0.7,
            proposal_id="gen1-001",
        )
        assert p.clusters_touched == ("C4 Macro",)
        assert p.diff == {"extreme_deviation_pct": 15.0}
        assert p.self_score.self_score == 0.7

    def test_clusters_touched_must_be_nonempty(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            make_proposal(
                clusters_touched=(),
                diff={"x": 1.0},
                maker_intent="x",
                reasoning="x",
                self_score=0.5,
            )

    def test_diff_must_be_nonempty(self) -> None:
        with pytest.raises(ValueError, match="diff"):
            make_proposal(
                clusters_touched=("C1",),
                diff={},
                maker_intent="x",
                reasoning="x",
                self_score=0.5,
            )

    def test_diff_magnitude_clamped_to_50pct(self) -> None:
        with pytest.raises(ValueError, match="exceeds"):
            make_proposal(
                clusters_touched=("C1",),
                diff={"x": 75.0},
                maker_intent="x",
                reasoning="x",
                self_score=0.5,
            )

    def test_intent_length_capped(self) -> None:
        with pytest.raises(ValueError, match="maker_intent too long"):
            make_proposal(
                clusters_touched=("C1",),
                diff={"x": 1.0},
                maker_intent="x" * 100,
                reasoning="y",
                self_score=0.5,
            )

    def test_reasoning_length_capped(self) -> None:
        with pytest.raises(ValueError, match="reasoning too long"):
            make_proposal(
                clusters_touched=("C1",),
                diff={"x": 1.0},
                maker_intent="x",
                reasoning="y" * 300,
                self_score=0.5,
            )

    def test_clusters_accept_list_or_tuple(self) -> None:
        # List should be coerced to tuple for hashability.
        p = make_proposal(
            clusters_touched=["C1", "C2"],
            diff={"x": 1.0},
            maker_intent="x",
            reasoning="y",
            self_score=0.5,
        )
        assert isinstance(p.clusters_touched, tuple)

    def test_self_score_validates_via_dataclass(self) -> None:
        with pytest.raises(ValueError):
            make_proposal(
                clusters_touched=("C1",),
                diff={"x": 1.0},
                maker_intent="x",
                reasoning="y",
                self_score=1.5,
            )


# ---- Verdict --------------------------------------------------------------


class TestVerdict:
    def test_valid_verdict(self) -> None:
        v = make_verdict(
            candidate_id="abc123",
            checker_score=0.7,
            confidence=0.8,
            components={
                "cross_symbol_consistency": 0.7,
                "regime_robustness": 0.6,
            },
            flags=[],
            accept=True,
            feedback="looks ok",
        )
        assert v.accept is True
        assert v.components["regime_robustness"] == 0.6

    def test_score_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="checker_score"):
            make_verdict(
                candidate_id="x",
                checker_score=1.5,
                confidence=0.5,
                components={},
                accept=True,
                feedback="",
            )

    def test_confidence_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            make_verdict(
                candidate_id="x",
                checker_score=0.5,
                confidence=-0.1,
                components={},
                accept=True,
                feedback="",
            )

    def test_components_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="components"):
            make_verdict(
                candidate_id="x",
                checker_score=0.5,
                confidence=0.5,
                components={"x": 1.2},
                accept=True,
                feedback="",
            )

    def test_flag_must_have_severity_and_issue(self) -> None:
        with pytest.raises(ValueError, match="severity"):
            make_verdict(
                candidate_id="x",
                checker_score=0.5,
                confidence=0.5,
                components={},
                flags=[{"issue": "bad"}],
                accept=True,
                feedback="",
            )

    def test_flag_severity_enum(self) -> None:
        with pytest.raises(ValueError, match="severity"):
            make_verdict(
                candidate_id="x",
                checker_score=0.5,
                confidence=0.5,
                components={},
                flags=[{"severity": "critical", "issue": "x"}],
                accept=True,
                feedback="",
            )

    def test_feedback_length_capped(self) -> None:
        with pytest.raises(ValueError, match="feedback too long"):
            make_verdict(
                candidate_id="x",
                checker_score=0.5,
                confidence=0.5,
                components={},
                accept=True,
                feedback="x" * 300,
            )

    def test_raw_score_default_zero(self) -> None:
        v = make_verdict(
            candidate_id="x",
            checker_score=0.5,
            confidence=0.5,
            components={},
            accept=True,
            feedback="",
        )
        assert v.raw_score == 0.0


# ---- MergeResult ----------------------------------------------------------


class TestMergeResult:
    def test_valid(self) -> None:
        m = make_merge_result(
            final_decision="accepted",
            final_score=0.6,
            m4_verdict="promising",
            trigger_reasons=["m4_promising", "checker_accept"],
        )
        assert m.checker_confidence is None  # back-compat default

    def test_invalid_decision(self) -> None:
        with pytest.raises(ValueError, match="final_decision"):
            make_merge_result(
                final_decision="maybe",
                final_score=0.0,
                m4_verdict="promising",
                trigger_reasons=[],
            )

    def test_checker_confidence_validates(self) -> None:
        with pytest.raises(ValueError, match="checker_confidence"):
            make_merge_result(
                final_decision="accepted",
                final_score=0.0,
                m4_verdict="promising",
                trigger_reasons=[],
                checker_confidence=1.5,
            )

    def test_checker_confidence_none_is_valid(self) -> None:
        # Critical for back-compat: None must be allowed.
        m = make_merge_result(
            final_decision="accepted",
            final_score=0.0,
            m4_verdict="promising",
            trigger_reasons=[],
            checker_confidence=None,
        )
        assert m.checker_confidence is None


# ---- CalibrationParams ----------------------------------------------------


class TestCalibrationParams:
    def test_apply_clamps_to_unit_interval(self) -> None:
        # Use a wide (a, b) so sigmoid saturates; ensure output stays in [0, 1].
        c = make_calibration(a=10.0, b=-5.0, ece=0.01, n_samples=100)
        assert 0.0 <= c.apply(0.0) <= 1.0
        assert c.apply(0.0) < 0.5  # a*0 + b = -5 → sigmoid < 0.5
        assert c.apply(1.0) > 0.5  # a*1 + b = +5 → sigmoid > 0.5

    def test_apply_at_midpoint(self) -> None:
        # No-op calibration: a=1, b=0 → midpoint = sigmoid(0.5*1 + 0) ≈ 0.622
        c = make_calibration(a=1.0, b=0.0, ece=0.05, n_samples=10)
        mid = c.apply(0.5)
        assert abs(mid - 1 / (1 + 2.718281828459045 ** -0.5)) < 1e-6

    def test_out_of_range_raw_raises(self) -> None:
        c = make_calibration(a=1.0, b=0.0, ece=0.01, n_samples=10)
        with pytest.raises(ValueError):
            c.apply(-0.1)
        with pytest.raises(ValueError):
            c.apply(1.1)

    def test_n_samples_nonnegative(self) -> None:
        with pytest.raises(ValueError):
            make_calibration(a=1.0, b=0.0, ece=0.0, n_samples=-1)

    def test_ece_nonnegative(self) -> None:
        with pytest.raises(ValueError):
            make_calibration(a=1.0, b=0.0, ece=-0.1, n_samples=10)