"""Tests for D-FT-19 verdict helpers.

`suggest_verdict` returns one of keep / revert / crash based on the
deterministic policy:
  1. CRASH if curr.max_dd > 2x baseline_drawdown (hard)
  2. KEEP if curr.sharpe >= prev AND curr.max_dd <= prev AND win_rate >= floor
  3. REVERT otherwise

The reasoning string is always non-empty and >= REASONING_MIN_LENGTH.
"""

from __future__ import annotations

import pytest

from app.ft_strategy.supabase_repo import ReasoningEmpty
from app.ft_strategy.verdict import (
    ALL_VERDICTS,
    MetricsSnapshot,
    VERDICT_CRASH,
    VERDICT_KEEP,
    VERDICT_REVERT,
    assert_reasoning_satisfies_d_ft_19,
    suggest_verdict,
)
from app.loop.tuning_promotion_v3 import REASONING_MIN_LENGTH, DRAWDOWN_MULTIPLIER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snap(
    sharpe: float = 1.5,
    max_dd: float = 0.08,
    win_rate: float = 0.60,
    profit_pct: float = 0.10,
) -> MetricsSnapshot:
    return MetricsSnapshot(
        sharpe=sharpe,
        max_dd=max_dd,
        win_rate=win_rate,
        profit_pct=profit_pct,
    )


# ---------------------------------------------------------------------------
# Verdict policy
# ---------------------------------------------------------------------------


class TestCrashRule:
    def test_hard_crash_when_dd_exceeds_2x_baseline(self):
        # baseline 0.05 -> threshold 0.10; curr 0.15 -> crash
        prev = _snap(max_dd=0.08)
        curr = _snap(max_dd=0.15)
        result = suggest_verdict(prev, curr, baseline_drawdown=0.05)
        assert result.verdict == VERDICT_CRASH
        assert result.is_hard_rule

    def test_crash_precedence_even_with_better_sharpe(self):
        # sharpe improves but DD exceeds threshold -> still crash
        prev = _snap(sharpe=1.0, max_dd=0.05, win_rate=0.60)
        curr = _snap(sharpe=2.0, max_dd=0.15, win_rate=0.70)
        result = suggest_verdict(prev, curr, baseline_drawdown=0.05)
        assert result.verdict == VERDICT_CRASH

    def test_at_threshold_is_not_crash(self):
        # curr.max_dd == threshold (not >)
        prev = _snap(max_dd=0.04)
        curr = _snap(max_dd=0.10)  # == 2 * 0.05
        result = suggest_verdict(prev, curr, baseline_drawdown=0.05)
        # Falls through to keep/revert logic — here sharpe unchanged, dd worse => revert
        assert result.verdict == VERDICT_REVERT
        assert not result.is_hard_rule

    def test_below_threshold_is_safe(self):
        prev = _snap(sharpe=1.0, max_dd=0.10)
        curr = _snap(sharpe=1.2, max_dd=0.09)
        result = suggest_verdict(prev, curr, baseline_drawdown=0.10)
        assert result.verdict == VERDICT_KEEP


class TestKeepRule:
    def test_keep_when_all_three_improvements(self):
        prev = _snap(sharpe=1.0, max_dd=0.10, win_rate=0.55)
        curr = _snap(sharpe=1.2, max_dd=0.08, win_rate=0.60)
        result = suggest_verdict(prev, curr, baseline_drawdown=1.0)  # way above any DD
        assert result.verdict == VERDICT_KEEP

    def test_keep_when_sharpe_unchanged(self):
        # Equality allowed (>=)
        prev = _snap(sharpe=1.5, max_dd=0.10, win_rate=0.55)
        curr = _snap(sharpe=1.5, max_dd=0.09, win_rate=0.60)
        result = suggest_verdict(prev, curr, baseline_drawdown=1.0)
        assert result.verdict == VERDICT_KEEP

    def test_keep_when_dd_unchanged(self):
        prev = _snap(sharpe=1.0, max_dd=0.10, win_rate=0.55)
        curr = _snap(sharpe=1.5, max_dd=0.10, win_rate=0.60)
        result = suggest_verdict(prev, curr, baseline_drawdown=1.0)
        assert result.verdict == VERDICT_KEEP


class TestRevertRule:
    def test_revert_when_sharpe_regresses(self):
        prev = _snap(sharpe=1.5, max_dd=0.10, win_rate=0.55)
        curr = _snap(sharpe=1.4, max_dd=0.05, win_rate=0.70)
        result = suggest_verdict(prev, curr, baseline_drawdown=1.0)
        assert result.verdict == VERDICT_REVERT

    def test_revert_when_dd_worsens(self):
        prev = _snap(sharpe=1.0, max_dd=0.05, win_rate=0.55)
        curr = _snap(sharpe=1.5, max_dd=0.08, win_rate=0.70)  # dd worse (0.08 > 0.05)
        result = suggest_verdict(prev, curr, baseline_drawdown=1.0)
        assert result.verdict == VERDICT_REVERT

    def test_revert_when_win_rate_below_floor(self):
        prev = _snap(sharpe=1.0, max_dd=0.10, win_rate=0.55)
        curr = _snap(sharpe=1.5, max_dd=0.05, win_rate=0.40)  # 0.40 < 0.50 floor
        result = suggest_verdict(prev, curr, baseline_drawdown=1.0)
        assert result.verdict == VERDICT_REVERT

    def test_revert_when_custom_min_win_rate_higher(self):
        prev = _snap(sharpe=1.0, max_dd=0.10, win_rate=0.65)
        curr = _snap(sharpe=1.5, max_dd=0.05, win_rate=0.60)  # 0.60 < 0.70 floor
        result = suggest_verdict(prev, curr, baseline_drawdown=1.0, min_win_rate=0.70)
        assert result.verdict == VERDICT_REVERT


class TestReasoning:
    def test_reasoning_always_long_enough(self):
        cases = [
            # (prev, curr, baseline) sets
            (_snap(sharpe=1.5, max_dd=0.10), _snap(sharpe=1.0, max_dd=0.20), 0.10),  # crash
            (_snap(sharpe=1.0, max_dd=0.10), _snap(sharpe=1.5, max_dd=0.05), 1.0),  # keep
            (_snap(sharpe=2.0, max_dd=0.05), _snap(sharpe=1.0, max_dd=0.10), 1.0),  # revert
        ]
        for prev, curr, baseline in cases:
            r = suggest_verdict(prev, curr, baseline_drawdown=baseline)
            assert len(r.reasoning) >= REASONING_MIN_LENGTH, (
                f"reasoning too short: {r.reasoning!r}"
            )

    def test_reasoning_mentions_keeper_metrics(self):
        prev = _snap(sharpe=1.0)
        curr = _snap(sharpe=2.0)
        result = suggest_verdict(prev, curr, baseline_drawdown=1.0)
        assert "1.0000" in result.reasoning or "KEEP" in result.reasoning


class TestDefensiveTypeCheck:
    def test_non_snapshot_prev_raises(self):
        with pytest.raises(TypeError):
            suggest_verdict({"not": "a snapshot"}, _snap(), baseline_drawdown=0.05)  # type: ignore[arg-type]

    def test_non_snapshot_curr_raises(self):
        with pytest.raises(TypeError):
            suggest_verdict(_snap(), {"not": "a snapshot"}, baseline_drawdown=0.05)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# assert_reasoning_satisfies_d_ft_19
# ---------------------------------------------------------------------------


class TestDft19Enforcement:
    def test_accepts_long_enough_reasoning(self):
        assert_reasoning_satisfies_d_ft_19(
            "Sharpe 1.5 holds across all regimes tested; drawdown within budget"
        )

    def test_rejects_short_reasoning(self):
        with pytest.raises(ReasoningEmpty):
            assert_reasoning_satisfies_d_ft_19("too short")

    def test_rejects_empty_string(self):
        with pytest.raises(ReasoningEmpty):
            assert_reasoning_satisfies_d_ft_19("")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ReasoningEmpty):
            assert_reasoning_satisfies_d_ft_19("          ")

    def test_rejects_non_string(self):
        with pytest.raises(ReasoningEmpty):
            assert_reasoning_satisfies_d_ft_19(42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestExports:
    def test_all_verdicts_count(self):
        assert len(ALL_VERDICTS) == 3

    def test_all_verdicts_values(self):
        assert set(ALL_VERDICTS) == {"keep", "revert", "crash"}

    def test_baseline_drawdown_multiplier_default(self):
        # smoke: 2x is the contract
        assert DRAWDOWN_MULTIPLIER == 2.0


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_metrics_snapshot_frozen(self):
        s = _snap()
        with pytest.raises(Exception):
            s.sharpe = 99.0  # type: ignore[misc]

    def test_verdict_result_frozen(self):
        r = suggest_verdict(_snap(sharpe=1.0), _snap(sharpe=2.0), baseline_drawdown=1.0)
        with pytest.raises(Exception):
            r.verdict = "crash"  # type: ignore[misc]
