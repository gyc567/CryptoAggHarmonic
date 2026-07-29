"""Tests for :mod:`app.loop.maker_checker.arbiter`.

Covers: ArbiterConfig validation, all 6 branches of the decision tree,
weighted merge arithmetic, 5-D Pareto back-compat.
"""
from __future__ import annotations

import pytest

from app.loop.checker import CheckerVerdict
from app.loop.maker_checker.arbiter import (
    Arbiter,
    ArbiterConfig,
    is_5d_backcompat,
    pareto_score,
    resolve,
)
from app.loop.maker_checker.schemas import (
    MergeResult,
    Proposal,
    Verdict,
    make_merge_result,
    make_proposal,
    make_verdict,
)


# ---- Helpers --------------------------------------------------------------


def _m4(decision: str, confidence: float = 0.7) -> CheckerVerdict:
    return CheckerVerdict(
        candidate_id="cand",
        decision=decision,
        confidence=confidence,
        reasons=[],
        flags=[],
    )


def _llm(
    *,
    accept: bool,
    score: float = 0.6,
    confidence: float = 0.7,
    candidate_id: str = "cand",
) -> Verdict:
    return make_verdict(
        candidate_id=candidate_id,
        checker_score=score,
        confidence=confidence,
        components={},
        flags=[],
        accept=accept,
        feedback="x",
    )


def _maker(self_score: float) -> Proposal:
    return make_proposal(
        clusters_touched=("C1",),
        diff={"x": 1.0},
        maker_intent="i",
        reasoning="r",
        self_score=self_score,
    )


# ---- ArbiterConfig --------------------------------------------------------


class TestArbiterConfig:
    def test_defaults(self) -> None:
        c = ArbiterConfig()
        assert c.maker_weight == 0.4
        assert c.checker_weight == 0.6

    def test_weights_sum_to_one(self) -> None:
        # Already defaults; sanity check.
        c = ArbiterConfig()
        assert abs(c.maker_weight + c.checker_weight - 1.0) < 0.01

    def test_weights_must_sum_to_one(self) -> None:
        with pytest.raises(ValueError, match="must equal 1.0"):
            ArbiterConfig(maker_weight=0.3, checker_weight=0.5)

    def test_negative_weight(self) -> None:
        with pytest.raises(ValueError, match="maker_weight"):
            ArbiterConfig(maker_weight=-0.1, checker_weight=1.1)

    def test_too_large_weight(self) -> None:
        with pytest.raises(ValueError, match="checker_weight"):
            ArbiterConfig(maker_weight=0.0, checker_weight=1.5)

    def test_gap_threshold_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="maker_checker_gap_threshold"):
            ArbiterConfig(maker_checker_gap_threshold=1.5)


# ---- Decision tree --------------------------------------------------------


class TestDecisionTree:
    def test_m4_rejected_overrides_llm_accept(self) -> None:
        m = resolve(m4=_m4("rejected"), llm=_llm(accept=True))
        assert m.final_decision == "rejected"

    def test_m4_rejected_overrides_llm_reject(self) -> None:
        m = resolve(m4=_m4("rejected"), llm=_llm(accept=False))
        assert m.final_decision == "rejected"

    def test_m4_promising_llm_accept_accepted(self) -> None:
        m = resolve(m4=_m4("promising"), llm=_llm(accept=True))
        assert m.final_decision == "accepted"

    def test_m4_promising_llm_reject_rejected(self) -> None:
        m = resolve(m4=_m4("promising"), llm=_llm(accept=False))
        assert m.final_decision == "rejected"

    def test_m4_suspicious_llm_accept_human(self) -> None:
        m = resolve(m4=_m4("suspicious"), llm=_llm(accept=True))
        assert m.final_decision == "suspicious_to_human"

    def test_m4_suspicious_llm_reject_rejected(self) -> None:
        m = resolve(m4=_m4("suspicious"), llm=_llm(accept=False))
        assert m.final_decision == "rejected"

    def test_large_gap_with_llm_accept_diverts_to_human(self) -> None:
        cfg = ArbiterConfig(maker_checker_gap_threshold=0.3)
        m = resolve(
            m4=_m4("promising"),
            llm=_llm(accept=True, score=0.9),
            maker=_maker(0.0),  # gap = 0.9
            config=cfg,
        )
        assert m.final_decision == "suspicious_to_human"

    def test_unknown_m4_decision_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown m4 decision"):
            resolve(m4=_m4("maybe"), llm=_llm(accept=True))


# ---- Weighted merge -------------------------------------------------------


class TestWeightedMerge:
    def test_score_is_weighted(self) -> None:
        # maker=0.8, checker=0.4, weights 0.4/0.6 → 0.4*0.8 + 0.6*0.4 = 0.56
        m = resolve(
            m4=_m4("promising"),
            llm=_llm(accept=True, score=0.4),
            maker=_maker(0.8),
        )
        assert m.final_score == pytest.approx(0.56, abs=1e-6)

    def test_score_with_no_maker_uses_default(self) -> None:
        m = resolve(m4=_m4("promising"), llm=_llm(accept=True, score=0.4))
        # maker defaults to 0.5 → 0.4*0.5 + 0.6*0.4 = 0.44
        assert m.final_score == pytest.approx(0.44, abs=1e-6)


# ---- 5-D Pareto back-compat -----------------------------------------------


class TestFiveDBackCompat:
    def test_pareto_score_includes_checker_confidence(self) -> None:
        m = make_merge_result(
            final_decision="accepted",
            final_score=0.6,
            m4_verdict="promising",
            trigger_reasons=[],
            checker_confidence=0.85,
        )
        score = pareto_score(m, base_metrics={
            "sharpe": 1.2, "calmar": 1.5, "profit_factor": 1.4,
            "worst_regime_sharpe": 0.3,
        })
        assert score["checker_confidence"] == 0.85
        assert score["sharpe"] == 1.2

    def test_is_5d_backcompat_with_none(self) -> None:
        assert is_5d_backcompat({"checker_confidence": None}) is True

    def test_is_5d_backcompat_with_missing_key(self) -> None:
        assert is_5d_backcompat({}) is True

    def test_is_5d_backcompat_with_value(self) -> None:
        assert is_5d_backcompat({"checker_confidence": 0.5}) is False

    def test_pareto_score_handles_none_metrics(self) -> None:
        m = make_merge_result(
            final_decision="accepted",
            final_score=0.6,
            m4_verdict="promising",
            trigger_reasons=[],
            checker_confidence=None,
        )
        score = pareto_score(m, base_metrics={})
        assert score["sharpe"] == 0.0
        assert score["checker_confidence"] is None


# ---- Trigger reasons ------------------------------------------------------


class TestTriggers:
    def test_includes_m4_state(self) -> None:
        m = resolve(m4=_m4("rejected"), llm=_llm(accept=False))
        assert "m4_rejected" in m.trigger_reasons

    def test_includes_human_review_marker(self) -> None:
        m = resolve(m4=_m4("suspicious"), llm=_llm(accept=True))
        assert any("suspicious" in t for t in m.trigger_reasons)