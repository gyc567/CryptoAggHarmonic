"""Unit tests for app.services.discipline_filters.

Covers the three live-trading gates (path-integrity, TTL, TP2) plus the
dist-pct helper. Tests use synthetic 100-bar DataFrames with hand-crafted
PRZ and price action so the verdicts are deterministic without standing up
real market data.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.domain.signals import Candidate
from app.services.discipline_filters import (
    DEFAULT_TTL_BARS,
    DisciplineResult,
    evaluate,
)


def _make_df(closes, lows=None, highs=None) -> pd.DataFrame:
    """Build a minimal DataFrame with high/low/close columns.

    ``lows`` / ``highs`` default to ``close ± 0.5``.
    """
    n = len(closes)
    lows = lows if lows is not None else [c - 0.5 for c in closes]
    highs = highs if highs is not None else [c + 0.5 for c in closes]
    opens = [closes[0]] + list(closes[:-1])
    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [100.0] * n,
    })


def _bullish_candidate(prz_low=100.0, prz_high=102.0, c_idx=50,
                      a=110.0, d=102.0) -> Candidate:
    """A bullish gartley with X=95, A=110, B=100, C=107, D=102.

    R/R targets for a bullish gartley:
      TP1 = D + 0.382*(A-D) = 102 + 0.382*8 = 105.06
      TP2 = D + 0.618*(A-D) = 102 + 0.618*8 = 106.94
    """
    return Candidate(
        family="XABCD",
        name="gartley",
        bullish=True,
        formed=False,
        points=(95.0, a, 100.0, 107.0, d),
        completion_min=prz_low,
        completion_max=prz_high,
        times=(40, 45, 48, c_idx, 0),
    )


def _bearish_candidate(prz_low=98.0, prz_high=100.0, c_idx=50,
                      a=90.0, d=98.0) -> Candidate:
    """A bearish gartley with X=105, A=90, B=100, C=95, D=98.

    R/R targets for a bearish gartley:
      TP2 = D - 0.618*(A-D) = 98 - 0.618*(90-98) = 98 - 0.618*(-8) = 98 + 4.94 = 102.94

    Wait — D > A for bearish, so A-D is negative. TP2 = D - 0.618*(D-A) is the
    standard formula: 98 - 0.618*(98-90) = 98 - 0.618*8 = 93.06.
    """
    return Candidate(
        family="XABCD",
        name="gartley",
        bullish=False,
        formed=False,
        points=(105.0, a, 100.0, 95.0, d),
        completion_min=prz_low,
        completion_max=prz_high,
        times=(40, 45, 48, c_idx, 0),
    )


class TestEvaluateHappyPath:
    def test_fresh_candidate_passes(self):
        # 50 bars at 85 (below PRZ), then 50 bars at 105 (above PRZ high=102).
        # Bar 51: low=104.5 > 102 → no breach. Current=105 < TP2=106.94.
        closes = [85.0] * 50 + [105.0] * 50
        df = _make_df(closes)
        cand = _bullish_candidate()
        result = evaluate(df, cand, current_price=closes[-1], max_ttl=60)
        assert isinstance(result, DisciplineResult)
        assert result.passed is True
        assert result.metrics.stale is False
        assert result.metrics.breached_stop is False
        assert result.metrics.past_tp2 is False
        assert result.metrics.in_prz is False
        assert result.metrics.dist_pct > 0

    def test_default_ttl_is_40_bars(self):
        assert DEFAULT_TTL_BARS == 40


class TestPathIntegrity:
    def test_bullish_wick_into_prz_marks_breached(self):
        # 60 bars: first 50 at 100 (C at 50), then 10 bars at 110 with bar 59
        # wicking down to low=99 (touches PRZ [100, 102]).
        closes = [100.0] * 50 + [110.0] * 10   # 60 bars
        highs = [100.5] * 50 + [101.0] * 10
        lows = [99.5] * 50 + [99.0] * 10
        df = _make_df(closes, highs=highs, lows=lows)
        cand = _bullish_candidate(prz_low=100, prz_high=102, c_idx=50)
        result = evaluate(df, cand, current_price=110.0, max_ttl=60)
        assert result.metrics.breached_stop is True
        assert result.passed is False

    def test_bearish_wick_into_prz_marks_breached(self):
        # 60 bars: first 50 at 90 (C at 50), then 10 bars at 95 with bar 59
        # wicking up to high=99 (touches PRZ [98, 100]).
        closes = [90.0] * 50 + [95.0] * 10
        lows = [89.5] * 50 + [98.0] * 10
        highs = [90.5] * 50 + [99.5] * 10
        df = _make_df(closes, lows=lows, highs=highs)
        cand = _bearish_candidate(prz_low=98, prz_high=100, c_idx=50)
        result = evaluate(df, cand, current_price=95.0, max_ttl=60)
        assert result.metrics.breached_stop is True

    def test_close_above_prz_without_wick_does_not_breach(self):
        # All bars entirely above PRZ [100, 102].
        closes = [110.0] * 60
        lows = [109.5] * 60
        highs = [110.5] * 60
        df = _make_df(closes, lows=lows, highs=highs)
        cand = _bullish_candidate(prz_low=100, prz_high=102, c_idx=50)
        result = evaluate(df, cand, current_price=110.0, max_ttl=60)
        assert result.metrics.breached_stop is False


class TestTTL:
    def test_stale_marks_but_passes(self):
        # 100 bars at 105 (above PRZ high=102, so no breach). C at idx=90.
        # bars_since_c = 99-90 = 9 > 5 (TTL) → stale. Price=105 < TP2=106.94.
        closes = [105.0] * 100
        df = _make_df(closes)
        cand = _bullish_candidate(prz_low=100, prz_high=102, c_idx=90)
        result = evaluate(df, cand, current_price=105.0, max_ttl=5)
        assert result.metrics.stale is True
        # Master gate does NOT exclude stale candidates — only breaching does.
        assert result.passed is True

    def test_not_stale_within_ttl(self):
        closes = [100.0] * 100
        df = _make_df(closes)
        cand = _bullish_candidate(prz_low=100, prz_high=102, c_idx=90)
        result = evaluate(df, cand, current_price=100.0, max_ttl=60)
        assert result.metrics.stale is False


class TestTP2:
    def test_bullish_past_tp2_excludes(self):
        # 100 bars rising to 119.8; price > TP2 (106.94) → past_tp2.
        closes = [100 + i * 0.2 for i in range(100)]
        df = _make_df(closes)
        cand = _bullish_candidate(prz_low=102, prz_high=104, c_idx=50)
        result = evaluate(df, cand, current_price=closes[-1], max_ttl=60)
        assert result.metrics.past_tp2 is True
        assert result.passed is False

    def test_bearish_past_tp2_excludes(self):
        # 100 bars falling to 80; price < TP2 (93.06) → past_tp2.
        closes = [100 - i * 0.2 for i in range(100)]
        df = _make_df(closes)
        cand = _bearish_candidate(prz_low=96, prz_high=98, c_idx=50)
        result = evaluate(df, cand, current_price=closes[-1], max_ttl=60)
        assert result.metrics.past_tp2 is True
        assert result.passed is False


class TestDistPct:
    def test_distance_above_prz(self):
        closes = [110.0] * 100
        df = _make_df(closes)
        cand = _bullish_candidate(prz_low=100, prz_high=102, c_idx=50)
        result = evaluate(df, cand, current_price=110.0, max_ttl=60)
        # 110 / 102 - 1 ≈ 7.84%
        assert 7.5 < result.metrics.dist_pct < 8.5

    def test_in_prz_distance_zero(self):
        closes = [101.0] * 100
        df = _make_df(closes)
        cand = _bullish_candidate(prz_low=100, prz_high=102, c_idx=50)
        result = evaluate(df, cand, current_price=101.0, max_ttl=60)
        assert result.metrics.in_prz is True
        assert result.metrics.dist_pct == 0.0


class TestCIdxFallback:
    def test_recovers_c_idx_from_candidate_times(self):
        # If caller passes c_idx=None, recover from candidate.times[-2].
        closes = [100.0] * 100
        df = _make_df(closes)
        cand = _bullish_candidate(prz_low=100, prz_high=102, c_idx=80)
        result = evaluate(df, cand, current_price=100.0, max_ttl=5)
        # bars_since_c = 99 - 80 = 19 > 5 → stale.
        assert result.metrics.stale is True
