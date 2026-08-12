"""Tests for v3 multi-objective promotion gate (D-FT-23).

Pure-function coverage: every branch of ``check_promotion_v3`` must be exercised,
plus the defensive type-check path and the Pareto-dominance helper.
"""

from __future__ import annotations

import pytest

from app.loop.tuning_promotion_v3 import (
    CRASH_CLOSURE_WINDOW_DAYS,
    DEFAULT_PROFIT_FLOOR,
    DEFAULT_ROBUST_SHARPE_MIN,
    DRAWDOWN_MULTIPLIER,
    PerTimerangeResult,
    PromotionCandidate,
    PromotionContext,
    STAGNATION_ROUNDS,
    assert_crash_closure_window,
    check_promotion_v3,
    module_constants,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _regime(sharpe: float, calmar: float = 1.0, max_dd: float = 0.10, regime: str = "full_5y") -> PerTimerangeResult:
    return PerTimerangeResult(regime=regime, sharpe=sharpe, max_dd=max_dd, calmar=calmar)


def _candidate(
    *,
    sharpe: float = 1.5,
    max_dd: float = 0.08,
    calmar: float = 2.0,
    win_rate: float = 0.6,
    profit_pct: float = 0.10,
    trades: int = 50,
    per_timerange: tuple = (_regime(1.5, 2.0, 0.08),),
    has_final_report: bool = True,
    open_crash_in_window_days: int = 0,
    version: int = 1,
    strategy_id: str = "strat-1",
) -> PromotionCandidate:
    return PromotionCandidate(
        strategy_id=strategy_id,
        version=version,
        sharpe=sharpe,
        max_dd=max_dd,
        calmar=calmar,
        win_rate=win_rate,
        profit_pct=profit_pct,
        trades=trades,
        per_timerange=per_timerange,
        has_final_report=has_final_report,
        open_crash_in_window_days=open_crash_in_window_days,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_all_eight_pass_with_default_ctx(self):
        result = check_promotion_v3(_candidate())
        assert result.ok, [i.label for i in result.failing_items()]
        assert len(result.items) == 8
        assert result.hard_blockers == ()

    def test_passing_result_exposes_all_8_items(self):
        result = check_promotion_v3(_candidate())
        labels = [i.label for i in result.items]
        assert labels == [
            "robust_sharpe_min",
            "robust_calmar_min",
            "max_drawdown",
            "profit_floor",
            "min_position_size",
            "not_pareto_dominated",
            "report_referenced",
            "no_open_crash_in_window",
        ]

    def test_none_ctx_uses_defaults(self):
        # ctx=None -> uses module defaults; should still be ok for healthy candidate
        result = check_promotion_v3(_candidate(), ctx=None)
        assert result.ok


# ---------------------------------------------------------------------------
# Each item in isolation
# ---------------------------------------------------------------------------


class TestRobustSharpeMin:
    def test_fails_when_min_regime_sharpe_below_floor(self):
        c = _candidate(
            per_timerange=(
                _regime(1.5, regime="bull"),
                _regime(-0.05, regime="winter"),  # negative -> below 0.0 floor
                _regime(0.5, regime="recovery"),
            )
        )
        result = check_promotion_v3(c)
        assert not result.ok
        item = next(i for i in result.items if i.label == "robust_sharpe_min")
        assert not item.passed
        assert item.observed == pytest.approx(-0.05, abs=1e-4)
        assert item.threshold == DEFAULT_ROBUST_SHARPE_MIN

    def test_passes_when_all_regimes_above_floor(self):
        c = _candidate(
            per_timerange=(
                _regime(1.5, regime="bull"),
                _regime(0.5, regime="winter"),  # 0.5 > 0.0
                _regime(0.7, regime="recovery"),
            )
        )
        result = check_promotion_v3(c)
        assert result.ok

    def test_fails_when_per_timerange_missing(self):
        c = _candidate(per_timerange=())
        result = check_promotion_v3(c)
        assert not result.ok
        item = next(i for i in result.items if i.label == "robust_sharpe_min")
        assert item.note == "no per_timerange rows; cannot evaluate"


class TestRobustCalmarMin:
    def test_fails_when_min_calmar_below_floor(self):
        c = _candidate(
            per_timerange=(
                _regime(1.5, calmar=2.5, regime="bull"),
                _regime(0.5, calmar=0.4, regime="winter"),  # < 1.0 default floor
                _regime(0.7, calmar=1.5, regime="recovery"),
            )
        )
        result = check_promotion_v3(c)
        assert not result.ok
        item = next(i for i in result.items if i.label == "robust_calmar_min")
        assert not item.passed
        assert item.observed == pytest.approx(0.4, abs=1e-4)
        assert item.threshold == 1.0


class TestMaxDrawdown:
    def test_fails_above_threshold(self):
        # baseline default 0.156; threshold 2x = 0.312; 0.40 must fail
        c = _candidate(max_dd=0.40)
        result = check_promotion_v3(c)
        item = next(i for i in result.items if i.label == "max_drawdown")
        assert not item.passed

    def test_passes_at_or_below_threshold(self):
        c = _candidate(max_dd=0.156 * DRAWDOWN_MULTIPLIER)
        result = check_promotion_v3(c)
        item = next(i for i in result.items if i.label == "max_drawdown")
        assert item.passed

    def test_custom_baseline(self):
        # Custom baseline 0.05 -> threshold 0.10
        c = _candidate(max_dd=0.15)
        ctx = PromotionContext(baseline_drawdown=0.05)
        result = check_promotion_v3(c, ctx)
        item = next(i for i in result.items if i.label == "max_drawdown")
        assert not item.passed  # 0.15 > 0.10


class TestProfitFloor:
    def test_fails_below_floor(self):
        c = _candidate(profit_pct=0.01)
        result = check_promotion_v3(c)
        item = next(i for i in result.items if i.label == "profit_floor")
        assert not item.passed
        assert item.threshold == DEFAULT_PROFIT_FLOOR

    def test_passes_at_or_above_floor(self):
        c = _candidate(profit_pct=0.05)
        result = check_promotion_v3(c)
        item = next(i for i in result.items if i.label == "profit_floor")
        assert item.passed


class TestMinPositionSize:
    def test_fails_below_floor(self):
        c = _candidate(trades=10)
        result = check_promotion_v3(c)
        item = next(i for i in result.items if i.label == "min_position_size")
        assert not item.passed

    def test_passes_at_floor(self):
        c = _candidate(trades=30)
        result = check_promotion_v3(c)
        item = next(i for i in result.items if i.label == "min_position_size")
        assert item.passed


class TestParetoDominance:
    def test_dominated_when_prior_is_strictly_better(self):
        # Prior KEEP with strictly better (s, c, -dd, wr) — candidate is dominated
        c = _candidate(sharpe=1.0, calmar=1.5, max_dd=0.10, win_rate=0.55)
        prior = (1.2, 1.8, -0.08, 0.60)
        ctx = PromotionContext(prior_keep_shapes=(prior,))
        result = check_promotion_v3(c, ctx)
        item = next(i for i in result.items if i.label == "not_pareto_dominated")
        assert not item.passed

    def test_passes_when_no_priors(self):
        c = _candidate()
        ctx = PromotionContext(prior_keep_shapes=())
        result = check_promotion_v3(c, ctx)
        item = next(i for i in result.items if i.label == "not_pareto_dominated")
        assert item.passed

    def test_passes_when_prior_is_equal_not_strictly_better(self):
        # Equal in all coords => not strictly dominating
        c = _candidate(sharpe=1.5, calmar=2.0, max_dd=0.08, win_rate=0.60)
        prior = (1.5, 2.0, -0.08, 0.60)
        ctx = PromotionContext(prior_keep_shapes=(prior,))
        result = check_promotion_v3(c, ctx)
        item = next(i for i in result.items if i.label == "not_pareto_dominated")
        assert item.passed

    def test_passes_when_candidate_is_strictly_better_in_some_dim(self):
        # Candidate beats prior in sharpe (1.5 > 1.0) -> not dominated
        c = _candidate(sharpe=1.5, calmar=1.5, max_dd=0.10, win_rate=0.55)
        prior = (1.0, 1.8, -0.08, 0.60)
        ctx = PromotionContext(prior_keep_shapes=(prior,))
        result = check_promotion_v3(c, ctx)
        item = next(i for i in result.items if i.label == "not_pareto_dominated")
        assert item.passed

    def test_partial_pareto_strictly_dominates(self):
        # Prior better on 3 dims but worse on 1 (calmar): not strictly dominating
        # because candidate.calmar (2.0) > prior.calmar (1.0), so not ge_all.
        c = _candidate(sharpe=1.5, calmar=2.0, max_dd=0.10, win_rate=0.55)
        prior = (2.0, 1.0, -0.05, 0.70)
        ctx = PromotionContext(prior_keep_shapes=(prior,))
        result = check_promotion_v3(c, ctx)
        item = next(i for i in result.items if i.label == "not_pareto_dominated")
        assert item.passed


class TestReportReferenced:
    def test_fails_when_no_final_report(self):
        c = _candidate(has_final_report=False)
        result = check_promotion_v3(c)
        item = next(i for i in result.items if i.label == "report_referenced")
        assert not item.passed

    def test_passes_when_final_report_present(self):
        c = _candidate(has_final_report=True)
        result = check_promotion_v3(c)
        item = next(i for i in result.items if i.label == "report_referenced")
        assert item.passed


class TestCrashClosure:
    def test_fails_when_open_crash_in_window(self):
        c = _candidate(open_crash_in_window_days=1)
        result = check_promotion_v3(c)
        item = next(i for i in result.items if i.label == "no_open_crash_in_window")
        assert not item.passed
        assert "7 day" in item.note

    def test_passes_when_no_open_crashes(self):
        c = _candidate(open_crash_in_window_days=0)
        result = check_promotion_v3(c)
        item = next(i for i in result.items if i.label == "no_open_crash_in_window")
        assert item.passed


# ---------------------------------------------------------------------------
# Multiple failures
# ---------------------------------------------------------------------------


class TestMultipleFailures:
    def test_hard_blockers_lists_all_failing(self):
        c = _candidate(
            sharpe=0.5,
            max_dd=0.50,  # way above 2x baseline
            profit_pct=-0.10,
            trades=5,
            has_final_report=False,
            open_crash_in_window_days=2,
            per_timerange=(_regime(-0.5, calmar=0.1),),
        )
        ctx = PromotionContext(prior_keep_shapes=((2.0, 3.0, -0.05, 0.7),))
        result = check_promotion_v3(c, ctx)
        assert not result.ok
        # Should fail almost every item
        assert "max_drawdown" in result.hard_blockers
        assert "profit_floor" in result.hard_blockers
        assert "min_position_size" in result.hard_blockers
        assert "report_referenced" in result.hard_blockers
        assert "no_open_crash_in_window" in result.hard_blockers

    def test_failing_items_helper(self):
        c = _candidate(profit_pct=-0.5, trades=5)
        result = check_promotion_v3(c)
        failing = result.failing_items()
        assert all(not i.passed for i in failing)
        labels = {i.label for i in failing}
        assert "profit_floor" in labels
        assert "min_position_size" in labels
        assert "no_open_crash_in_window" not in labels


# ---------------------------------------------------------------------------
# Defensive type-check path
# ---------------------------------------------------------------------------


class TestTypeCheck:
    def test_non_promotioncandidate_returns_failed_result(self):
        result = check_promotion_v3({"not": "a candidate"})  # type: ignore[arg-type]
        assert not result.ok
        assert result.hard_blockers == ("type_check",)
        assert "candidate must be PromotionCandidate" in result.items[0].note

    def test_non_promotioncontext_returns_failed_result(self):
        result = check_promotion_v3(_candidate(), ctx={"not": "a context"})  # type: ignore[arg-type]
        assert not result.ok
        assert result.hard_blockers == ("type_check",)
        assert "context must be PromotionContext" in result.items[0].note


# ---------------------------------------------------------------------------
# Dataclass immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_promotioncandidate_is_frozen(self):
        c = _candidate()
        with pytest.raises(Exception):
            c.sharpe = 99.0  # type: ignore[misc]

    def test_promotionresult_is_frozen(self):
        r = check_promotion_v3(_candidate())
        with pytest.raises(Exception):
            r.ok = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestAssertCrashClosureWindow:
    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            assert_crash_closure_window(-1)

    def test_over_90_rejected(self):
        with pytest.raises(ValueError):
            assert_crash_closure_window(91)

    def test_non_int_rejected(self):
        with pytest.raises(TypeError):
            assert_crash_closure_window(7.0)  # type: ignore[arg-type]

    def test_zero_ok(self):
        assert assert_crash_closure_window(0) == 0

    def test_seven_ok(self):
        # module default window
        assert assert_crash_closure_window(CRASH_CLOSURE_WINDOW_DAYS) == 7

    def test_90_ok(self):
        # edge of upper bound
        assert assert_crash_closure_window(90) == 90


class TestModuleConstants:
    def test_keys_present(self):
        constants = module_constants()
        # These exact literal values must be echoed via the capabilities endpoint (D-FT-16).
        assert constants["MCP_TIMEOUT_SECONDS"] == 1800
        assert constants["MAX_BACKTEST_PER_GEN"] == 5
        assert constants["STAGNATION_ROUNDS"] == STAGNATION_ROUNDS
        assert constants["RESEARCH_MD_MIN_LENGTH"] == 200
        assert constants["REASONING_MIN_LENGTH"] == 10
        assert constants["CRASH_CLOSURE_WINDOW_DAYS"] == 7

    def test_keys_complete(self):
        # Snapshot test: protects against accidental key removal
        keys = sorted(module_constants().keys())
        assert keys == sorted([
            "MCP_TIMEOUT_SECONDS",
            "MAX_BACKTEST_PER_GEN",
            "STAGNATION_ROUNDS",
            "RESEARCH_MD_MIN_LENGTH",
            "REASONING_MIN_LENGTH",
            "CRASH_CLOSURE_WINDOW_DAYS",
            "DEFAULT_PROFIT_FLOOR",
            "DEFAULT_MIN_POSITION_SIZE",
            "DEFAULT_ROBUST_SHARPE_MIN",
            "DEFAULT_ROBUST_CALMAR_MIN",
            "DEFAULT_DRAWDOWN_BASELINE",
            "DRAWDOWN_MULTIPLIER",
        ])


# ---------------------------------------------------------------------------
# PerTimerangeResult
# ---------------------------------------------------------------------------


class TestPerTimerangeResult:
    def test_construction(self):
        r = PerTimerangeResult("bull_2021", 1.5, 0.05, 2.0)
        assert r.regime == "bull_2021"
        assert r.sharpe == 1.5
        assert r.max_dd == 0.05
        assert r.calmar == 2.0

    def test_frozen(self):
        r = PerTimerangeResult("x", 1.0, 0.1, 1.0)
        with pytest.raises(Exception):
            r.sharpe = 99.0  # type: ignore[misc]
