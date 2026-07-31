"""Tests for bench.scoring.confidence."""

from __future__ import annotations

import math

import pytest

from bench.dataset.signal_record import empty_record
from bench.scoring.confidence import _z_for_alpha, bh_fdr, low_confidence, wilson_ci


# ---------- wilson_ci ----------

def test_wilson_ci_perfect_zero_n_returns_full_range() -> None:
    assert wilson_ci(0, 0) == (0.0, 1.0)


def test_wilson_ci_perfect_50_percent_centered() -> None:
    lower, upper = wilson_ci(50, 100)
    assert lower < 0.5 < upper
    # Symmetric around 0.5
    assert math.isclose(upper - 0.5, 0.5 - lower, abs_tol=1e-4)


def test_wilson_ci_all_successes_clamps_to_one() -> None:
    lower, upper = wilson_ci(100, 100)
    # upper clamps to ≤ 1.0 (may be 0.9999... due to float math)
    assert upper == pytest.approx(1.0)
    # For 100/100, Wilson lower is ≈ 0.963, not 1.0
    assert 0.95 <= lower <= 1.0


def test_wilson_ci_no_successes_lower_is_zero() -> None:
    lower, upper = wilson_ci(0, 100)
    assert lower == 0.0
    assert upper > 0.0  # but not 1.0


def test_wilson_ci_one_of_one_is_wide() -> None:
    lower, upper = wilson_ci(1, 1)
    # 1/1 = 1.0; Wilson CI is wide for tiny samples
    assert lower >= 0.0
    assert upper <= 1.0


def test_wilson_ci_invalid_successes_raises() -> None:
    with pytest.raises(ValueError):
        wilson_ci(-1, 10)
    with pytest.raises(ValueError):
        wilson_ci(11, 10)


def test_wilson_ci_invalid_alpha_raises() -> None:
    with pytest.raises(ValueError):
        wilson_ci(5, 10, alpha=0.0)
    with pytest.raises(ValueError):
        wilson_ci(5, 10, alpha=1.0)
    with pytest.raises(ValueError):
        wilson_ci(5, 10, alpha=-0.1)


def test_wilson_ci_alpha_99_has_wider_bounds_than_95() -> None:
    _, upper_95 = wilson_ci(50, 100, alpha=0.05)
    _, upper_99 = wilson_ci(50, 100, alpha=0.01)
    assert upper_99 > upper_95


def test_wilson_ci_in_unit_range() -> None:
    lower, upper = wilson_ci(7, 20)
    assert 0.0 <= lower <= upper <= 1.0


# ---------- _z_for_alpha ----------

def test_z_for_alpha_known_values() -> None:
    assert _z_for_alpha(0.05) == pytest.approx(1.96)
    assert _z_for_alpha(0.01) == pytest.approx(2.5758)


def test_z_for_alpha_unknown_raises() -> None:
    with pytest.raises(ValueError):
        _z_for_alpha(0.07)


# ---------- bh_fdr ----------

def test_bh_fdr_empty_returns_empty() -> None:
    adjusted, reject = bh_fdr([])
    assert adjusted == []
    assert reject == []


def test_bh_fdr_single_significant() -> None:
    adjusted, reject = bh_fdr([0.001])
    assert reject == [True]
    assert adjusted[0] >= 0.001  # never smaller than raw p


def test_bh_fdr_single_not_significant() -> None:
    adjusted, reject = bh_fdr([0.5])
    assert reject == [False]


def test_bh_fdr_monotonic_in_adjusted_order() -> None:
    """Adjusted p-values should be non-decreasing when p-values are sorted."""
    pvalues = [0.001, 0.01, 0.05, 0.2, 0.5]
    adjusted, _ = bh_fdr(pvalues)
    # Sort by original index order is meaningless; instead, check adjusted
    # at each rank matches a non-decreasing sequence when sorted by raw p.
    paired = sorted(zip(pvalues, adjusted))
    for i in range(1, len(paired)):
        assert paired[i][1] >= paired[i - 1][1] - 1e-9


def test_bh_fdr_adjusted_in_unit_range() -> None:
    pvalues = [0.001, 0.01, 0.05, 0.2, 0.5]
    adjusted, _ = bh_fdr(pvalues)
    for p in adjusted:
        assert 0.0 <= p <= 1.0


def test_bh_fdr_invalid_alpha_raises() -> None:
    with pytest.raises(ValueError):
        bh_fdr([0.01, 0.02], alpha=0.0)
    with pytest.raises(ValueError):
        bh_fdr([0.01, 0.02], alpha=1.0)


def test_bh_fdr_invalid_pvalue_raises() -> None:
    with pytest.raises(ValueError):
        bh_fdr([-0.1, 0.5])
    with pytest.raises(ValueError):
        bh_fdr([0.5, 1.5])


def test_bh_fdr_classic_example() -> None:
    """Classical BH example: 5 hypotheses at 0.01, 0.02, 0.03, 0.04, 0.05.

    Sorted ranks (1..5): BH thresholds = 0.01×5/1=0.05, 0.02×5/2=0.05,
    0.03×5/3=0.05, 0.04×5/4=0.05, 0.05×5/5=0.05. So all 5 reject at α=0.05.
    """
    pvalues = [0.01, 0.02, 0.03, 0.04, 0.05]
    _, reject = bh_fdr(pvalues, alpha=0.05)
    assert all(reject)


def test_bh_fdr_only_one_rejects() -> None:
    """One significant p-value + several non-significant."""
    pvalues = [0.001, 0.5, 0.6, 0.7]
    _, reject = bh_fdr(pvalues, alpha=0.05)
    assert reject == [True, False, False, False]


def test_bh_fdr_zero_pvalue_kept_significant() -> None:
    adjusted, reject = bh_fdr([0.0, 0.5, 0.9])
    assert reject[0] is True
    assert reject[1] is False


# ---------- low_confidence ----------

def test_low_confidence_empty_is_low() -> None:
    assert low_confidence([]) is True


def test_low_confidence_small_n_is_low() -> None:
    # default min_n=30
    records = [empty_record(outcome="tp1") for _ in range(10)]
    assert low_confidence(records) is True


def test_low_confidence_sufficient_n_all_wins() -> None:
    records = [empty_record(outcome="tp1") for _ in range(50)]
    assert low_confidence(records) is False


def test_low_confidence_sufficient_n_all_losses() -> None:
    # 0/50 → Wilson lower < 0.4 → low_confidence (via lower branch)
    records = [empty_record(outcome="stoploss") for _ in range(50)]
    assert low_confidence(records) is True


def test_low_confidence_upper_below_max_upper_branch() -> None:
    """Hit the second branch (`upper < max_upper`): enough wins to clear
    min_lower, but the upper bound still below max_upper (low-confidence
    even though the lower bound is OK)."""
    # 100 wins / 1000 trials → Wilson CI ≈ (0.082, 0.122)
    # min_lower=0.05: lower=0.082 ≥ 0.05, so first branch passes.
    # max_upper=0.5: upper=0.122 < 0.5, returns True via upper branch.
    records = (
        [empty_record(outcome="tp1") for _ in range(100)]
        + [empty_record(outcome="stoploss") for _ in range(900)]
    )
    assert low_confidence(records, min_n=10, min_lower=0.05, max_upper=0.5) is True


def test_low_confidence_mixed_above_threshold() -> None:
    # 30/50 wins → 60% win rate, Wilson CI should span 0.4–0.6+
    records = (
        [empty_record(outcome="tp1") for _ in range(30)]
        + [empty_record(outcome="stoploss") for _ in range(20)]
    )
    assert low_confidence(records) is False


def test_low_confidence_explicit_false_path() -> None:
    """Hit the `return False` line: n >= min_n, lower >= min_lower,
    upper >= max_upper."""
    records = [empty_record(outcome="tp1") for _ in range(40)]
    # min_lower=0.5, max_upper=0.5: Wilson CI for 40/40 = (~0.91, 1.0)
    # both bounds clear, returns False.
    assert low_confidence(records, min_n=10, min_lower=0.5, max_upper=0.5) is False


def test_low_confidence_custom_thresholds() -> None:
    # 100 records all wins → high confidence
    records = [empty_record(outcome="tp1") for _ in range(100)]
    # Tight thresholds: not low
    assert low_confidence(records, min_n=10, min_lower=0.9, max_upper=0.95) is False


def test_low_confidence_low_win_rate_threshold() -> None:
    # 100 records, 50 wins → 50% win rate
    records = (
        [empty_record(outcome="tp1") for _ in range(50)]
        + [empty_record(outcome="stoploss") for _ in range(50)]
    )
    # min_lower=0.6 forces it to be low
    assert low_confidence(records, min_n=10, min_lower=0.6, max_upper=0.4) is True
