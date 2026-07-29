"""Layer-2 contract tests for app.domain.signals.

icontract's ``@require`` / ``@ensure`` decorators turn business invariants into
runtime checks; this file locks down their behaviour. Each test pins one
precondition or postcondition so a future refactor can't silently weaken the
contract without breaking a test.

These tests are pure (no I/O, no fixtures, no monkey-patching) so they run
in <50ms and can be the first thing CI executes when investigating a
signal-engine regression.
"""

from __future__ import annotations

import pytest
from icontract import ViolationError

from app.domain.signals import (
    Candidate,
    compute_stop,
    grade,
    net_rr,
)

# ---------------------------------------------------------------------------
# Helpers — keep the candidate-construction boilerplate in one place
# ---------------------------------------------------------------------------


def _candidate(
    *,
    bullish: bool = True,
    formed: bool = True,
    points: tuple = (100.0, 110.0, 95.0, 105.0, 100.0),
    prz_low: float = 99.0,
    prz_high: float = 101.0,
    name: str = "gartley",
    family: str = "XABCD",
) -> Candidate:
    """Build a deterministic Candidate for contract tests.

    Defaults produce a bullish Gartley with a 99..101 PRZ; override only the
    fields under test.
    """
    return Candidate(
        family=family,
        name=name,
        bullish=bullish,
        formed=formed,
        points=points,
        completion_min=prz_low,
        completion_max=prz_high,
    )


# ---------------------------------------------------------------------------
# compute_stop
# ---------------------------------------------------------------------------


class TestComputeStopContracts:
    """compute_stop's @require/@ensure invariants.

    Pure layer-2 tests — no market data, no orchestrator.
    """

    def test_rejects_zero_atr(self):
        with pytest.raises(ViolationError, match="ATR must be positive"):
            compute_stop(_candidate(), atr=0.0)

    def test_rejects_negative_atr(self):
        with pytest.raises(ViolationError, match="ATR must be positive"):
            compute_stop(_candidate(), atr=-1.0)

    def test_rejects_zero_prz(self):
        cand = _candidate(prz_low=0.0, prz_high=101.0)
        with pytest.raises(ViolationError, match="PRZ bounds must be positive"):
            compute_stop(cand, atr=2.0)

    def test_rejects_zero_pivot(self):
        # A harmonic pivot at price=0 is meaningless and would break the
        # anchor computation downstream.
        cand = _candidate(points=(100.0, 0.0, 95.0, 105.0, 100.0))
        with pytest.raises(ViolationError, match="pivot prices must all be positive"):
            compute_stop(cand, atr=2.0)

    def test_ensure_positive_stop(self):
        # No way to construct a violating call from the public API given the
        # requires above, but the @ensure is still load-bearing for the
        # internal return contract — sanity-check the happy path produces a
        # positive stop.
        stop, basis, invalidation = compute_stop(_candidate(), atr=2.0)
        assert stop > 0
        assert invalidation > 0
        assert len(basis) > 0
        assert "ATR" in basis  # basis always names the buffer

    def test_unknown_level_coerced_to_standard_silently(self):
        """Document the *intentional* non-contract: invalid levels fall back.

        compute_stop does NOT @require ``level in STOP_LOSS_LEVELS`` — it
        silently coerces unknown levels to "standard" rather than raising.
        This test pins that behaviour so any future refactor that flips it
        to raise has to consciously update this test (which is exactly the
        point of a contract test).
        """
        stop_a, _, _ = compute_stop(_candidate(), atr=2.0, level="standard")
        stop_b, _, _ = compute_stop(_candidate(), atr=2.0, level="bogus")
        assert stop_a == stop_b


# ---------------------------------------------------------------------------
# net_rr
# ---------------------------------------------------------------------------


class TestNetRrContracts:
    """net_rr pre/post-conditions: positive entry/stop/target, non-negative fees."""

    def test_rejects_zero_entry(self):
        with pytest.raises(ViolationError, match="Entry price must be positive"):
            net_rr(0.0, 95.0, 110.0)

    def test_rejects_zero_stop(self):
        with pytest.raises(ViolationError, match="Stop price must be positive"):
            net_rr(100.0, 0.0, 110.0)

    def test_rejects_zero_target(self):
        with pytest.raises(ViolationError, match="Target price must be positive"):
            net_rr(100.0, 95.0, 0.0)

    def test_rejects_negative_fee(self):
        with pytest.raises(ViolationError, match="fee_rate must be non-negative"):
            net_rr(100.0, 95.0, 110.0, fee_rate=-0.001)

    def test_rejects_negative_slippage(self):
        with pytest.raises(ViolationError, match="slippage_rate must be non-negative"):
            net_rr(100.0, 95.0, 110.0, slippage_rate=-0.001)

    def test_zero_risk_returns_none(self):
        # entry/stop positive but identical — risk = 0.
        # The internal ``if risk <= 0`` short-circuit returns None without
        # touching the ensure.
        assert net_rr(100.0, 100.0, 110.0) is None

    def test_negative_reward_returns_none(self):
        # Reward < cost → still a valid call, postcondition says result is None.
        assert net_rr(100.0, 50.0, 100.1) is None

    def test_positive_rr_is_positive(self):
        # Pure net R/R on a clean entry/stop/target.
        rr = net_rr(entry=100.0, stop=95.0, target=110.0)
        assert rr is not None and rr > 0


# ---------------------------------------------------------------------------
# grade
# ---------------------------------------------------------------------------


class TestGradeContracts:
    """grade's @require/@ensure: score in [0,100], exclusive htf booleans."""

    def test_rejects_negative_score(self):
        with pytest.raises(ViolationError, match="score must be a 0-100"):
            grade(-1, 2.0, 3.0, True, False)

    def test_rejects_score_above_100(self):
        with pytest.raises(ViolationError, match="score must be a 0-100"):
            grade(150, 2.0, 3.0, True, False)

    def test_rejects_a_min_zero(self):
        with pytest.raises(ViolationError, match="a_min must be in"):
            grade(80, 2.0, 3.0, True, False, a_min=0)

    def test_rejects_a_min_above_100(self):
        with pytest.raises(ViolationError, match="a_min must be in"):
            grade(80, 2.0, 3.0, True, False, a_min=200)

    def test_rejects_aligned_and_counter_both_true(self):
        with pytest.raises(ViolationError, match="Aligned and counter cannot both"):
            grade(80, 2.0, 3.0, htf_aligned=True, htf_counter=True)

    def test_returns_none_when_rr_inputs_none(self):
        # grade() internal short-circuit on None RR.
        assert grade(80, None, None, True, False) is None

    def test_returns_known_grade_on_happy_path(self):
        g = grade(80, 2.0, 3.0, True, False)
        assert g in ("A", "B", "C(参考)")


# ---------------------------------------------------------------------------
# Integration smoke: signal pipeline goes through the contracts cleanly.
# ---------------------------------------------------------------------------


class TestSignalPipelineContractPath:
    """End-to-end smoke: build_signal flows through compute_stop → net_rr → grade
    without violating any contract on a realistic candidate.
    """

    def test_realistic_gartley_signal_passes_all_contracts(self):
        import pandas as pd

        from app.services.signal_engine import build_signal

        # Synthetic 200-bar 1h candle frame: monotonic up trend with a
        # shallow pullback at bar 150 so the engine has room to compute.
        n = 200
        base = 100.0
        closes = [base + i * 0.05 for i in range(n)]
        # Inject a small pullback around bar 150 so PRZ has structure.
        for i in range(145, 160):
            closes[i] = closes[i] - 1.5
        df = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 0.5 for c in closes],
                "low": [c - 0.5 for c in closes],
                "close": closes,
                "volume": [1000.0] * n,
            }
        )

        cand = _candidate(
            bullish=True,
            formed=True,
            points=(99.0, 110.0, 102.0, 108.0, 100.5),
            prz_low=99.5,
            prz_high=101.0,
        )
        # No exception means every contract on the public pipeline passed.
        signal = build_signal(
            df,
            interval="1h",
            candidates=[cand],
            divergences={},
        )
        # Signal may be None (grade gate) — that's fine, the contract path
        # only forbids silently-broken intermediate values.
        if signal is not None:
            assert signal.stop_loss > 0
            assert signal.entry_reference > 0
            assert signal.grade in ("A", "B", "C(参考)")
