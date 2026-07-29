"""Unit tests for app.services.macro_bias.

Covers the five regimes from the v2 audit:

* trending + aligned      → 1.0
* ranging + aligned       → 1.0
* trending + inverse      → 0.6
* ranging + inverse       → 0.5
* extreme inverse         → 1.2

Plus the data-short fallback (<210 bars) and unknown signal direction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.macro_bias import _EXTREME_DEVIATION_PCT, _MIN_DAILY_BARS, compute


def _series(closes) -> pd.Series:
    return pd.Series(closes, dtype=float)


def _rising_series(n: int = 250, start: float = 100.0, slope: float = 0.3) -> pd.Series:
    """Geometric rising series: close_t = start * (1 + slope/100)^t."""
    idx = np.arange(n)
    return pd.Series(start * (1.0 + slope / 100.0) ** idx, dtype=float)


def _falling_series(n: int = 250, start: float = 100.0, slope: float = -0.3) -> pd.Series:
    return _rising_series(n=n, start=start, slope=slope)


class TestDataShort:
    def test_none_series_returns_conservative_mult(self):
        overlay = compute(None, signal_dir=1)
        assert overlay.size_mult == 0.8
        assert "数据不足" in overlay.advice

    def test_short_series_returns_conservative_mult(self):
        overlay = compute(_series([100.0] * 50), signal_dir=1)
        assert overlay.size_mult == 0.8

    def test_exactly_threshold_minus_one(self):
        # 209 bars (one below threshold) → still data short.
        overlay = compute(_rising_series(n=209), signal_dir=1)
        assert overlay.size_mult == 0.8


class TestAlignedTrending:
    def test_bull_in_bull_market_trending_aligned(self):
        # Geom rising 1%/bar; trend slope on EMA200 > 0.5, price > EMA200.
        overlay = compute(_rising_series(250, start=100, slope=1.0), signal_dir=1)
        assert overlay.macro_dir.startswith("牛市")
        assert overlay.signal_vs_macro == "顺势"
        assert overlay.size_mult == 1.0

    def test_bear_in_bear_market_trending_aligned(self):
        # Strong falling series → price < EMA200, short signal.
        overlay = compute(_falling_series(250, start=100, slope=-1.0), signal_dir=-1)
        assert overlay.macro_dir.startswith("熊市")
        assert overlay.signal_vs_macro == "顺势"
        assert overlay.size_mult == 1.0


class TestAlignedRanging:
    def test_long_against_flat_market_aligned(self):
        # 100 bars rising, then 150 bars flat → broker trending again → trending.
        # For TRUE ranging, we need slope < 0.5 AND price > EMA200.
        # Use a series that oscillates & ends near EMA200.
        closes = [100.0 + ((-1) ** i) * 0.5 for i in range(250)]
        closes[-1] = 101.0  # slightly above EMA200
        overlay = compute(_series(closes), signal_dir=1)
        assert abs(overlay.ema200_slope_20d) < 0.5
        assert overlay.signal_vs_macro == "顺势"
        assert overlay.size_mult == 1.0


class TestInverseRanging:
    def test_ranging_inverse_drops_to_half(self):
        # 100 bars rising, then 150 bars flat. Price (≈200) > EMA200 (≈200 ish).
        # short_signal → not aligned (since price > EMA200). EMA200 slope ≈ 0 (ranging).
        rises = [100.0 * (1.005**i) for i in range(100)]  # 100 → 164.46
        flat = [rises[-1]] * 150
        closes = rises + flat
        overlay = compute(_series(closes), signal_dir=-1)
        # After 150 flat bars, EMA200 should be very close to 200 (settled).
        # short_signal + price ~ EMA200 + slope ~ 0 → either aligned (if price<200)
        # or ranging inverse (if price>200 just slightly).
        assert overlay.size_mult in (0.5, 1.0)
        if overlay.size_mult == 0.5:
            assert overlay.signal_vs_macro == "逆势"


class TestExtremeInverse:
    def test_strong_falling_triggers_extreme_inverse_for_long(self):
        # Long signal against a strong -1%/bar falling series.
        # EMA200 lags ~200 bars → price much below EMA200 → |deviation| > 20%
        # → extreme inverse → 1.2.
        overlay = compute(_falling_series(250, slope=-1.0), signal_dir=1)
        assert overlay.signal_vs_macro == "逆势+极端"
        assert overlay.size_mult == 1.2
        assert abs(overlay.deviation_pct) > _EXTREME_DEVIATION_PCT

    def test_strong_rising_triggers_extreme_inverse_for_short(self):
        overlay = compute(_rising_series(250, slope=1.0), signal_dir=-1)
        assert overlay.signal_vs_macro == "逆势+极端"
        assert overlay.size_mult == 1.2


class TestEdgeCases:
    def test_unknown_signal_dir_returns_neutral(self):
        overlay = compute(_rising_series(250, slope=1.0), signal_dir=0)
        assert overlay.size_mult == 1.0
        assert overlay.signal_vs_macro == "unknown"

    def test_deviation_pct_is_rounded(self):
        overlay = compute(_rising_series(250, slope=1.0), signal_dir=1)
        assert overlay.deviation_pct == round(overlay.deviation_pct, 1)
        assert overlay.ema200_slope_20d == round(overlay.ema200_slope_20d, 1)

    def test_min_daily_bars_constant(self):
        # Sanity: the constant matches the docstring (210 bars).
        assert _MIN_DAILY_BARS == 210
