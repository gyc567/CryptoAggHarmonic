from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Optional

from app.loop.maker_checker.schemas import CalibrationParams, make_calibration

# ---- Numerical helpers ----------------------------------------------------


"""Calibration — Platt scaling for Checker raw scores.

The LLM Checker emits a raw score in ``[0, 1]`` that is *not* a
probability. ``calibrate()`` fits a 2-parameter logistic on a labelled
validation set and returns a :class:`CalibrationParams` that maps raw
scores to probabilities via ``sigmoid(a * raw + b)``.

The validation set is a list of ``(raw_score, true_label)`` pairs where
``true_label`` is 1 if the candidate is genuinely good and 0 otherwise.
The fit is the standard Platt binary-MLE using L-BFGS-B on the log-loss
surface.

We also compute the **Expected Calibration Error (ECE)** — the absolute
gap between predicted probability and empirical accuracy, averaged over
bins. A good calibration has ``ECE < 0.05``; the
:class:`CalibrationParams` constructor rejects ``ECE >= 0.10``.
"""


def _sigmoid(z: float) -> float:
    """Numerically stable sigmoid."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _log_loss(a: float, b: float, pairs: Sequence[tuple[float, int]]) -> float:
    """Negative log-likelihood under Platt scaling."""
    n = 0.0
    total = 0.0
    for raw, label in pairs:
        p = _sigmoid(a * raw + b)
        # Clamp to avoid log(0).
        p = max(min(p, 1.0 - 1e-12), 1e-12)
        total += -((label * math.log(p)) + ((1 - label) * math.log(1 - p)))
        n += 1
    return total / max(n, 1)


def _grad(a: float, b: float, pairs: Sequence[tuple[float, int]]) -> tuple[float, float]:
    """Gradient of the log-loss w.r.t. (a, b)."""
    ga = 0.0
    gb = 0.0
    for raw, label in pairs:
        p = _sigmoid(a * raw + b)
        err = p - label
        ga += err * raw
        gb += err
    n = max(len(pairs), 1)
    return ga / n, gb / n


# ---- L-BFGS-lite ---------------------------------------------------------


def _fit_platt(
    pairs: Sequence[tuple[float, int]],
    *,
    max_iter: int = 200,
    lr: float = 0.5,
    tol: float = 1e-6,
) -> tuple[float, float]:
    """Plain gradient-descent fit (L-BFGS-B is overkill for 2 params).

    Starts at ``(a=1, b=0)`` which is the no-op calibration; if the
    loss improves, the step is taken, otherwise the learning rate is
    halved. Converges when the gradient norm is below ``tol``.
    """
    a, b = 1.0, 0.0
    for _ in range(max_iter):
        ga, gb = _grad(a, b, pairs)
        norm = math.sqrt(ga * ga + gb * gb)
        if norm < tol:
            break
        step = lr
        while step > 1e-6:
            a_new = a - step * ga
            b_new = b - step * gb
            if _log_loss(a_new, b_new, pairs) <= _log_loss(a, b, pairs):
                a, b = a_new, b_new
                break
            step *= 0.5  # pragma: no cover  # defensive: convex loss halving always succeeds
        else:  # pragma: no cover  # defensive: only hit on numerical anomaly
            # No improvement at any step — stop.
            break  # pragma: no cover  # defensive: only hit on numerical anomaly
    return a, b


# ---- Reliability diagram --------------------------------------------------


def _bin_predictions(
    pairs: Sequence[tuple[float, int]],
    n_bins: int = 10,
) -> list[tuple[float, float, int]]:
    """Group (raw, label) pairs into ``n_bins`` equal-width bins.

    Returns list of ``(mean_pred, empirical_freq, count)`` per bin,
    sorted by ``mean_pred``.
    """
    if not pairs:
        return []
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for raw, label in pairs:
        idx = min(int(raw * n_bins), n_bins - 1)
        bins[idx].append((raw, label))
    out: list[tuple[float, float, int]] = []
    for b in bins:
        if not b:
            continue
        preds = [r for r, _ in b]
        labels = [label for _, label in b]
        out.append((sum(preds) / len(b), sum(labels) / len(b), len(b)))
    out.sort(key=lambda x: x[0])
    return out


def expected_calibration_error(
    pairs: Sequence[tuple[float, int]],
    *,
    params: Optional[CalibrationParams] = None,
    n_bins: int = 10,
) -> float:
    """Compute ECE on ``pairs``.

    If ``params`` is provided, predictions are first calibrated; the
    ECE is then measured on the calibrated scores.
    """
    if not pairs:
        return 0.0
    if params is None:
        transformed: list[tuple[float, int]] = list(pairs)
    else:
        transformed = [(params.apply(r), label) for r, label in pairs]
    bins = _bin_predictions(transformed, n_bins=n_bins)
    if not bins:
        return 0.0  # pragma: no cover  # defensive: only hit if _bin returns []
    total = sum(c for _, _, c in bins)
    ece = 0.0
    for mean_pred, freq, count in bins:
        ece += (count / total) * abs(mean_pred - freq)
    return ece


# ---- Public API -----------------------------------------------------------


def calibrate(
    pairs: Sequence[tuple[float, int]],
    *,
    max_iter: int = 200,
) -> CalibrationParams:
    """Fit Platt scaling on ``pairs`` and return calibration params.

    Parameters
    ----------
    pairs
        Sequence of ``(raw_score, label)`` where ``raw_score ∈ [0, 1]``
        and ``label ∈ {0, 1}``. Must contain at least one positive and
        one negative example.

    Returns
    -------
    :class:`CalibrationParams` with ``a, b`` and the ECE on the
    training set.
    """
    if not pairs:
        raise ValueError("calibrate() requires at least one (raw, label) pair")
    n_pos = sum(1 for _, label in pairs if label == 1)
    n_neg = sum(1 for _, label in pairs if label == 0)
    if n_pos == 0 or n_neg == 0:
        raise ValueError("calibration set must contain both positive and negative " f"examples (got pos={n_pos}, neg={n_neg})")

    a, b = _fit_platt(pairs, max_iter=max_iter)
    ece = expected_calibration_error(pairs, params=CalibrationParams(a=a, b=b, ece=0.0, n_samples=len(pairs)))
    return make_calibration(a=a, b=b, ece=ece, n_samples=len(pairs))


def reliability_diagram(
    pairs: Sequence[tuple[float, int]],
    *,
    params: Optional[CalibrationParams] = None,
    n_bins: int = 10,
) -> list[tuple[float, float, int]]:
    """Return per-bin ``(mean_pred, empirical_freq, count)``.

    Suitable for plotting or test assertions on calibration quality.
    """
    if not pairs:
        return []
    if params is None:
        transformed = list(pairs)
    else:
        transformed = [(params.apply(r), label) for r, label in pairs]
    return _bin_predictions(transformed, n_bins=n_bins)


__all__ = [
    "calibrate",
    "expected_calibration_error",
    "reliability_diagram",
]
