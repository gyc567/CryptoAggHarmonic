"""Tests for :mod:`app.loop.maker_checker.calibration`.

Covers: Platt fitting on a known-logit signal, ECE on a perfectly
calibrated set vs a miscalibrated one, edge cases.
"""

from __future__ import annotations

import math

import pytest

from app.loop.maker_checker.calibration import (
    calibrate,
    expected_calibration_error,
    reliability_diagram,
)
from app.loop.maker_checker.schemas import CalibrationParams, make_calibration

# ---- Helpers --------------------------------------------------------------


def _gen_signal(
    n: int = 50,
    *,
    a: float = 3.0,
    b: float = -1.5,
    seed: int = 42,
) -> list[tuple[float, int]]:
    """Generate a (raw, label) set with known logistic relation.

    True probability is sigmoid(a * raw + b); label is sampled from
    Bernoulli(true_p). The fit should recover (a, b) approximately.
    """
    import random

    rng = random.Random(seed)
    out = []
    for _ in range(n):
        raw = rng.random()
        p = 1.0 / (1.0 + math.exp(-(a * raw + b)))
        label = 1 if rng.random() < p else 0
        out.append((raw, label))
    return out


# ---- calibrate ------------------------------------------------------------


class TestCalibrate:
    def test_recovers_logit_params(self) -> None:
        pairs = _gen_signal(n=200, a=4.0, b=-2.0)
        params = calibrate(pairs, max_iter=500)
        # Allow generous tolerance — gradient descent is noisy.
        assert abs(params.a - 4.0) < 1.5
        assert abs(params.b - (-2.0)) < 1.5

    def test_returns_calibration_params(self) -> None:
        pairs = _gen_signal(n=100)
        params = calibrate(pairs)
        assert isinstance(params, CalibrationParams)
        assert params.n_samples == 100
        assert params.ece >= 0.0

    def test_empty_input_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            calibrate([])

    def test_all_positive_raises(self) -> None:
        with pytest.raises(ValueError, match="both positive and negative"):
            calibrate([(0.1, 1), (0.5, 1), (0.9, 1)])

    def test_all_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="both positive and negative"):
            calibrate([(0.1, 0), (0.5, 0), (0.9, 0)])

    def test_low_ece_on_signal(self) -> None:
        # Strong signal → good calibration.
        pairs = _gen_signal(n=200, a=5.0, b=-2.5)
        params = calibrate(pairs, max_iter=500)
        assert params.ece < 0.10


# ---- expected_calibration_error -------------------------------------------


class TestECE:
    def test_perfect_calibration_yields_low_ece(self) -> None:
        # Generate samples where label is sampled with probability = raw.
        # Then empirical_freq in each bin ≈ mean_pred → low ECE.
        import random

        rng = random.Random(0)
        pairs = []
        for _ in range(2000):
            raw = rng.random()
            label = 1 if rng.random() < raw else 0
            pairs.append((raw, label))
        ece = expected_calibration_error(pairs)
        assert ece < 0.05

    def test_empty_returns_zero(self) -> None:
        assert expected_calibration_error([]) == 0.0

    def test_random_predictions_have_high_ece(self) -> None:
        # Mismatched preds and labels → high ECE.
        pairs = [(0.9, 0), (0.9, 0), (0.1, 1), (0.1, 1)]
        ece = expected_calibration_error(pairs)
        assert ece > 0.5

    def test_ece_with_params_transforms(self) -> None:
        # Calibration that maps 0.5 → 0.5 (a=0, b=0 → sigmoid(0)=0.5).
        params = make_calibration(a=0.0, b=0.0, ece=0.05, n_samples=10)
        pairs = [
            (0.5, 1),
            (0.5, 1),
            (0.5, 1),
            (0.5, 1),
            (0.5, 1),
            (0.5, 0),
            (0.5, 0),
            (0.5, 0),
            (0.5, 0),
            (0.5, 0),
        ]
        # All pairs in same bin (pred=0.5), empirical freq=0.5, gap=0 → ECE=0
        ece = expected_calibration_error(pairs, params=params)
        assert ece < 0.05


# ---- reliability_diagram --------------------------------------------------


class TestReliabilityDiagram:
    def test_empty_returns_empty(self) -> None:
        assert reliability_diagram([]) == []

    def test_returns_per_bin_summary(self) -> None:
        pairs = [(i / 9, 1 if i >= 5 else 0) for i in range(10)]
        bins = reliability_diagram(pairs, n_bins=10)
        # Each bin has one observation; should return 10 tuples.
        assert len(bins) == 10
        for mean_pred, freq, count in bins:
            assert 0.0 <= mean_pred <= 1.0
            assert 0.0 <= freq <= 1.0
            assert count == 1

    def test_sorted_by_mean_pred(self) -> None:
        pairs = [(0.2, 1), (0.8, 0), (0.5, 1), (0.1, 0)]
        bins = reliability_diagram(pairs, n_bins=5)
        means = [m for m, _, _ in bins]
        assert means == sorted(means)

    def test_applies_calibration_when_provided(self) -> None:
        # Calibration that doesn't shift 0.5 (a=0, b=0 → sigmoid(0)=0.5).
        params = make_calibration(a=0.0, b=0.0, ece=0.05, n_samples=10)
        pairs = [(0.5, 1)] * 10
        raw_bins = reliability_diagram(pairs, n_bins=10)
        cal_bins = reliability_diagram(pairs, params=params, n_bins=10)
        # No-shift calibration should yield same mean_pred.
        assert abs(raw_bins[0][0] - cal_bins[0][0]) < 0.01
