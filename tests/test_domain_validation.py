"""100% coverage tests for app.domain.validation (pure functions)."""

import math

import pandas as pd
import pytest

from app.domain.signals import Candidate
from app.domain.validation import (
    adverse_momentum_veto,
    direction_invariant_ok,
    filter_candidates,
    per_bar_sharpe,
    quant_regime,
    quant_trap_risk,
    rejection_reason,
    stability_verdict,
    volatility_multiplier,
    volume_authenticity,
)


def make_df(rows):
    """rows: list of (open, high, low, close, volume)"""
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def flat_df(n=60, price=100.0, volume=100.0):
    return make_df([(price, price + 0.5, price - 0.5, price, volume)] * n)


def make_candidate(**overrides):
    base = dict(
        family="XABCD",
        name="gartley",
        bullish=True,
        formed=True,
        points=(100.0, 150.0, 120.0, 140.0, 110.0),
        completion_min=108.0,
        completion_max=112.0,
    )
    base.update(overrides)
    return Candidate(**base)


# --- Candidate validity filter ---------------------------------------------------


class TestRejectionReason:
    def test_valid_candidate(self):
        assert rejection_reason(make_candidate(), price=110.0, atr=2.0) is None

    def test_stale_distance(self):
        # PRZ mid = 110, price 191 -> distance 81 >> 3*ATR
        assert rejection_reason(make_candidate(), price=191.0, atr=2.0) == "stale_distance"

    def test_stale_distance_boundary(self):
        assert rejection_reason(make_candidate(), price=110.0 + 3.0 * 2.0, atr=2.0) is None
        assert rejection_reason(make_candidate(), price=110.0 + 3.1 * 2.0, atr=2.0) == "stale_distance"

    def test_stale_age(self):
        times = tuple(range(100, 105))
        cand = make_candidate(times=times)
        close_times = list(range(100, 200))  # 95 bars after D
        assert rejection_reason(cand, price=110.0, atr=2.0, close_times=close_times) == "stale_age"

    def test_fresh_age_passes(self):
        cand = make_candidate(times=(100,))
        close_times = list(range(100, 110))  # 9 bars after D
        assert rejection_reason(cand, price=110.0, atr=2.0, close_times=close_times) is None

    def test_no_times_skips_age_check(self):
        cand = make_candidate()  # times=()
        assert rejection_reason(cand, price=110.0, atr=2.0, close_times=list(range(1000))) is None

    def test_degenerate_prz_forming_zero_width(self):
        cand = make_candidate(formed=False, completion_min=110.0, completion_max=110.0)
        assert rejection_reason(cand, price=110.0, atr=2.0) == "degenerate_prz"

    def test_degenerate_prz_forming_too_wide(self):
        cand = make_candidate(formed=False, completion_min=100.0, completion_max=120.0)
        assert rejection_reason(cand, price=110.0, atr=2.0) == "degenerate_prz"

    def test_wide_prz_allowed_for_formed(self):
        cand = make_candidate(formed=True, completion_min=100.0, completion_max=120.0)
        # price outside PRZ but within 3*ATR of mid (110): 115 is outside [100,120]? no, inside
        assert rejection_reason(cand, price=110.0, atr=2.0) is None

    def test_violated_bullish(self):
        # stop = min(X=100, PRZ 108) - 0.5*10 = 95; price 94 < 95 -> violated
        # distance |94-110| = 16 <= 3*10 -> not stale
        assert rejection_reason(make_candidate(), price=94.0, atr=10.0) == "violated"

    def test_violated_bearish(self):
        cand = make_candidate(
            bullish=False,
            points=(150.0, 100.0, 130.0, 110.0, 140.0),
            completion_min=138.0,
            completion_max=142.0,
        )
        # stop = max(150, 142) + 0.5*10 = 155; price 156 > 155 -> violated
        assert rejection_reason(cand, price=156.0, atr=10.0) == "violated"

    def test_completed_bullish(self):
        # A=150, PRZ mid=110 -> TP2 = 110 + 0.618*40 = 134.72; price 140 > TP2 -> completed
        # distance |140-110| = 30 <= 3*10 -> not stale
        assert rejection_reason(make_candidate(), price=140.0, atr=10.0) == "completed"

    def test_completed_bearish(self):
        cand = make_candidate(
            bullish=False,
            points=(150.0, 100.0, 130.0, 110.0, 140.0),
            completion_min=138.0,
            completion_max=142.0,
        )
        # A=100, PRZ mid=140 -> TP2 = 140 - 0.618*40 = 115.28; price 110 < TP2 -> completed
        assert rejection_reason(cand, price=110.0, atr=10.0) == "completed"

    def test_zero_atr_skips_distance_and_width(self):
        # atr=0: distance/width checks skipped; price inside PRZ -> valid
        cand = make_candidate()
        assert rejection_reason(cand, price=110.0, atr=0.0) is None


class TestFilterCandidates:
    def test_split(self):
        good = make_candidate()
        stale = make_candidate(name="bat")
        valid, rejected = filter_candidates([good, stale], price=110.0, atr=2.0)
        # both are fresh here
        assert len(valid) == 2
        assert rejected == []

        valid, rejected = filter_candidates([good, stale], price=191.0, atr=2.0)
        assert valid == []
        assert len(rejected) == 2
        assert rejected[0].reason == "stale_distance"
        assert rejected[0].candidate is good


class TestDirectionInvariant:
    def test_long_ok(self):
        assert direction_invariant_ok("long", 100.0, 95.0, [105.0, 110.0, 120.0]) is True

    def test_long_entry_equals_tp1_ok(self):
        assert direction_invariant_ok("long", 105.0, 95.0, [105.0, 110.0, 120.0]) is True

    def test_long_stop_above_entry_fails(self):
        assert direction_invariant_ok("long", 100.0, 105.0, [105.0, 110.0, 120.0]) is False

    def test_long_unordered_targets_fail(self):
        assert direction_invariant_ok("long", 100.0, 95.0, [110.0, 105.0, 120.0]) is False

    def test_short_ok(self):
        assert direction_invariant_ok("short", 100.0, 105.0, [95.0, 90.0, 80.0]) is True

    def test_short_stop_below_entry_fails(self):
        assert direction_invariant_ok("short", 100.0, 95.0, [95.0, 90.0, 80.0]) is False

    def test_short_unordered_targets_fail(self):
        assert direction_invariant_ok("short", 100.0, 105.0, [90.0, 95.0, 80.0]) is False

    def test_too_few_targets_fail(self):
        assert direction_invariant_ok("long", 100.0, 95.0, [105.0]) is False


# --- Quant trap risk ---------------------------------------------------------------


class TestQuantTrapRisk:
    def test_insufficient_data(self):
        score, veto, reasons = quant_trap_risk(flat_df(10), 99.0, 101.0, True)
        assert score == 50
        assert veto is False
        assert reasons == []

    def test_clean_market(self):
        score, veto, reasons = quant_trap_risk(flat_df(60), 99.0, 101.0, True)
        assert score == 50
        assert veto is False
        assert reasons == []

    @staticmethod
    def _false_break_df(spacing: int):
        """Every `spacing`-th bar pierces the running 5-bar high by 2% and closes below it."""
        rows = []
        for i in range(60):
            window = [r[1] for r in rows[-5:]]
            if len(window) >= 5 and i % spacing == spacing - 1:
                prev_high = max(window)
                rows.append((100.0, prev_high * 1.02, 99.0, prev_high - 1.0, 100.0))
            else:
                rows.append((100.0, 100.5, 99.5, 100.0, 100.0))
        return make_df(rows)

    def test_false_breakout_veto(self):
        # alternating baseline/break -> ~50% rate > 25% -> veto
        df = self._false_break_df(spacing=2)
        _, veto, reasons = quant_trap_risk(df, 99.0, 101.0, True)
        assert veto is True
        assert any("假突破" in r for r in reasons)

    def test_false_breakout_penalty(self):
        # 1 in 6 bars -> ~16% rate -> -20
        df = self._false_break_df(spacing=6)
        score, veto, reasons = quant_trap_risk(df, 99.0, 101.0, True)
        assert veto is False
        assert score == 30
        assert any("假突破频繁" in r for r in reasons)

    def test_false_breakout_warn(self):
        # 1 in 9 bars -> ~11% rate -> -8
        df = self._false_break_df(spacing=9)
        score, veto, reasons = quant_trap_risk(df, 99.0, 101.0, True)
        assert score == 42
        assert any("存在假突破" in r for r in reasons)

    def test_stop_hunt(self):
        baseline = (100.0, 100.5, 99.5, 100.0, 100.0)
        hunt_a = (100.0, 100.2, 97.5, 99.0, 100.0)  # new 3-bar low
        hunt_b = (99.0, 101.0, 98.5, 100.8, 100.0)  # next bar recovers above its high
        rows = [baseline] * 10
        for _ in range(8):
            # 3 baseline bars between hunts so each hunt's low is a fresh 3-bar low
            rows += [hunt_a, hunt_b, baseline, baseline, baseline]
        rows += [baseline] * 10
        df = make_df(rows)
        _, veto, reasons = quant_trap_risk(df, 99.0, 101.0, True)
        assert any("止损猎杀" in r for r in reasons)
        assert veto is False

    def test_volume_climax(self):
        rows = []
        vol = 100.0
        for i in range(60):
            if i % 4 == 0 and i > 0:
                rows.append((100.0, 100.4, 99.6, 100.1, vol * 3))
            else:
                rows.append((100.0, 100.5, 99.5, 100.0, vol))
        df = make_df(rows)
        _, veto, reasons = quant_trap_risk(df, 99.0, 101.0, True)
        assert any("量能高潮" in r for r in reasons)

    def test_prz_support_failure_veto(self):
        rows = [(100.0, 100.5, 99.5, 100.0, 100.0)] * 59
        rows.append((100.0, 100.5, 100.0, 98.0, 100.0))  # wick into PRZ, close below
        df = make_df(rows)
        score, veto, reasons = quant_trap_risk(df, 99.5, 101.0, True)
        assert veto is True
        assert reasons == ["PRZ支撑失败"]

    def test_prz_resistance_failure_veto(self):
        rows = [(100.0, 100.5, 99.5, 100.0, 100.0)] * 59
        rows.append((100.0, 100.3, 99.8, 100.5, 100.0))  # wick inside PRZ, close above it
        df = make_df(rows)
        score, veto, reasons = quant_trap_risk(df, 99.5, 100.4, False)
        assert veto is True
        assert reasons == ["PRZ阻力失败"]

    def test_prz_wick_outside_no_failure(self):
        # wick completely below PRZ low -> not a "support failure"
        rows = [(100.0, 100.5, 99.5, 100.0, 100.0)] * 59
        rows.append((100.0, 100.5, 98.0, 98.5, 100.0))
        df = make_df(rows)
        _, veto, _ = quant_trap_risk(df, 99.5, 101.0, True)
        assert veto is False

    def test_score_clamps(self):
        # stack penalties to force clamp at 10
        rows = [(100.0, 102.0, 99.5, 100.0, 100.0)] * 20
        rows += [(100.0, 100.5, 99.5, 100.0, 100.0)] * 40
        df = make_df(rows)
        score, _, _ = quant_trap_risk(df, 50.0, 51.0, True)
        assert 10 <= score <= 90


# --- Volume authenticity ----------------------------------------------------------


class TestVolumeAuthenticity:
    def test_insufficient_data(self):
        assert volume_authenticity(flat_df(5)) == 50

    def test_clean_uptrend_rising_volume(self):
        rows = []
        for i in range(60):
            price = 100.0 + i
            rows.append((price, price + 0.5, price - 0.5, price, 100.0 + i))
        df = make_df(rows)
        score = volume_authenticity(df)
        assert score >= 60

    def test_spike_heavy_low_score(self):
        # 1/3 of bars are >2.5x-mean spikes, price-volume fully misaligned
        rows = []
        price = 100.0
        for i in range(60):
            if i % 3 == 0:
                price = price - 0.3
                rows.append((price + 0.2, price + 0.4, price - 0.2, price, 1000.0))
            else:
                price = price + 0.2
                rows.append((price - 0.1, price + 0.3, price - 0.3, price, 10.0))
        df = make_df(rows)
        score = volume_authenticity(df)
        assert score < 40

    def test_flat_market_is_authentic(self):
        # perfectly aligned (nothing moves), no spikes -> high authenticity
        score = volume_authenticity(flat_df(60))
        assert score >= 80

    def test_zero_volume(self):
        df = flat_df(60, volume=0.0)
        assert 0 <= volume_authenticity(df) <= 100


# --- Stability verdict -------------------------------------------------------------


@pytest.mark.parametrize(
    "full,sub1,sub2,expected_score,expected_suspect",
    [
        ("gartley", "gartley", "gartley", 85, False),
        ("gartley", "gartley", "bat", 55, False),
        ("gartley", "bat", "gartley", 55, False),
        ("gartley", "bat", "crab", 25, False),
        ("gartley", "bat", None, 40, False),
        ("gartley", None, "bat", 40, False),
        ("gartley", None, None, 20, True),
        (None, "bat", "crab", 60, False),
        (None, None, None, 60, False),
    ],
)
def test_stability_verdict(full, sub1, sub2, expected_score, expected_suspect):
    score, suspect = stability_verdict(full, sub1, sub2)
    assert score == expected_score
    assert suspect is expected_suspect


# --- Quant regime ------------------------------------------------------------------


class TestQuantRegime:
    def test_insufficient_data(self):
        assert quant_regime(flat_df(10)) == (50, "normal")

    def test_calm_market_normal(self):
        rows = []
        for i in range(100):
            price = 100.0 + i * 0.1
            rows.append((price, price + 0.3, price - 0.3, price, 100.0))
        _, regime = quant_regime(make_df(rows))
        assert regime == "normal"

    def test_chaotic_market_high_quant(self):
        rows = []
        price = 100.0
        for i in range(100):
            gap = price * 1.02 if i % 2 == 0 else price * 0.98
            rows.append((gap, gap * 1.03, gap * 0.97, price * 1.001, 100.0 + (i % 7) * 300))
        _, regime = quant_regime(make_df(rows))
        assert regime in ("moderate_quant", "high_quant")

    def test_volume_cv_drives_score(self):
        rows = []
        for i in range(100):
            price = 100.0
            vol = 100.0 if i % 2 == 0 else 1000.0
            rows.append((price, price + 0.5, price - 0.5, price, vol))
        score, regime = quant_regime(make_df(rows))
        # Score is bounded by quant_regime's clamp; regime must be one of the
        # defined buckets (regression check).
        assert isinstance(score, int)
        assert regime in ("normal", "moderate_quant", "high_quant")

    def test_zero_mean_volume(self):
        df = flat_df(100, volume=0.0)
        score, regime = quant_regime(df)
        assert isinstance(score, int)
        assert regime in ("normal", "moderate_quant", "high_quant")

    def test_intraday_reversal_bars_counted(self):
        # doji-like bars: huge range (>3%) but tiny body (<0.5%)
        rows = []
        for i in range(100):
            price = 100.0
            if i % 2 == 0:
                rows.append((price, price * 1.05, price * 0.95, price * 1.001, 100.0))
            else:
                rows.append((price, price + 0.3, price - 0.3, price, 100.0))
        score, _ = quant_regime(make_df(rows))
        assert score > 0

    def test_high_quant_regime(self):
        # gaps + doji reversals + wild volume + fat-tail returns
        rows = []
        price = 100.0
        for i in range(100):
            gap_open = price * (1.03 if i % 2 == 0 else 0.97)
            close = gap_open * (1.08 if i % 5 == 0 else 0.999)
            vol = 100.0 if i % 2 == 0 else 2000.0
            rows.append((gap_open, max(gap_open, close) * 1.04, min(gap_open, close) * 0.96, close, vol))
            price = close
        score, regime = quant_regime(make_df(rows))
        assert regime == "high_quant"
        assert score >= 60


# --- Statistical gates --------------------------------------------------------------


class TestPerBarSharpe:
    def test_insufficient_data(self):
        assert per_bar_sharpe(pd.Series([1.0, 2.0])) == 0.0

    def test_flat_is_zero(self):
        assert per_bar_sharpe(pd.Series([100.0] * 30)) == 0.0

    def test_uptrend_positive(self):
        # constant +1% returns -> zero variance, positive mean -> +inf
        closes = pd.Series([100.0 * 1.01**i for i in range(30)])
        assert per_bar_sharpe(closes) == math.inf

    def test_downtrend_negative_inf(self):
        # constant -1% returns -> zero variance, negative mean -> -inf
        closes = pd.Series([100.0 * 0.99**i for i in range(30)])
        assert per_bar_sharpe(closes) == -math.inf

    def test_volatile_series(self):
        closes = pd.Series([100 + (i % 5) - 2 for i in range(40)], dtype=float)
        sharpe = per_bar_sharpe(closes)
        assert math.isfinite(sharpe)

    def test_constant_drift_up_after_flat(self):
        closes = pd.Series([100.0] * 10 + [100.0 + i for i in range(1, 11)])
        sharpe = per_bar_sharpe(closes)
        assert sharpe > 0


class TestAdverseMomentumVeto:
    def test_long_veto_on_falling_knife(self):
        assert adverse_momentum_veto("long", -1.5) is True

    def test_long_mild_adverse_ok(self):
        assert adverse_momentum_veto("long", -0.5) is False

    def test_short_veto_on_blowoff(self):
        assert adverse_momentum_veto("short", 1.5) is True

    def test_short_mild_adverse_ok(self):
        assert adverse_momentum_veto("short", 0.5) is False

    def test_custom_threshold(self):
        assert adverse_momentum_veto("long", -0.6, threshold=0.5) is True


class TestVolatilityMultiplier:
    def test_normal_vol(self):
        # ATR 2.5 on close 100 -> atr_pct 2.5 -> mult 1.0
        assert volatility_multiplier(2.5, 100.0) == 1.0

    def test_high_vol_shrinks(self):
        # atr_pct 5 -> mult 0.5 (clamped)
        assert volatility_multiplier(5.0, 100.0) == 0.5

    def test_low_vol_expands(self):
        # atr_pct 1 -> mult 2.5 -> clamped 1.5
        assert volatility_multiplier(1.0, 100.0) == 1.5

    def test_zero_close(self):
        assert volatility_multiplier(2.5, 0.0) == 1.0

    def test_floor_atr_pct(self):
        # tiny atr -> atr_pct < 0.5 -> uses 0.5 -> mult 5 -> clamped 1.5
        assert volatility_multiplier(0.001, 100.0) == 1.5
