"""Unit tests for the Q4 pattern-reliability weighting in signal_engine.

Verifies that:

* ``_pattern_base_score`` resolves the prefix of a pyharmonics-suffixed
  name (``"gartley-382-1"`` → +5).
* Unknown families return 0.
* ``score_candidate`` actually applies the bump to the confluence score
  (a Gartley must outrank a Crab at the same confluence and grade).
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.domain.signals import Candidate
from app.services.signal_engine import (
    PATTERN_BASE_SCORE,
    _pattern_base_score,
    _prepare_score_context,
    score_candidate,
)


def _make_df(n: int = 600) -> pd.DataFrame:
    """Build a strong uptrend with a hammer final bar (matches bullish_df)."""
    closes = [50.0 + i * 0.2 for i in range(n - 10)]
    peak = closes[-1]
    closes += [peak - 2.16 * (i + 1) for i in range(10)]
    closes[-1] = closes[-2] - 2.16
    rows = []
    for i, c in enumerate(closes):
        rows.append({
            "open": c,
            "high": c + 0.5,
            "low": c - 0.5,
            "close": c,
            "volume": 100.0,
            "close_time": 1_700_000_000 + i * 900,
        })
    df = pd.DataFrame(rows)
    df["dts"] = pd.to_datetime(df["close_time"], unit="s", utc=True)
    # Last bar: hammer with volume spike.
    df.loc[df.index[-1], "open"] = closes[-1] - 0.4
    df.loc[df.index[-1], "high"] = closes[-1] + 0.2
    df.loc[df.index[-1], "low"] = closes[-1] - 2.2
    df.loc[df.index[-1], "volume"] = 500.0
    return df


def _candidate(name: str) -> Candidate:
    return Candidate(
        family="XABCD",
        name=name,
        bullish=True,
        formed=True,
        points=(100.0, 110.0, 103.82, 107.64, 102.14),
        completion_min=102.0,
        completion_max=103.0,
        times=(10, 20, 30, 40, 50),
    )


class TestPatternBaseScoreLookup:
    def test_known_patterns_have_expected_bumps(self):
        assert PATTERN_BASE_SCORE["gartley"] == 5
        assert PATTERN_BASE_SCORE["bat"] == 2
        assert PATTERN_BASE_SCORE["butterfly"] == 0
        assert PATTERN_BASE_SCORE["crab"] == -3
        assert PATTERN_BASE_SCORE["deep crab"] == -5
        assert PATTERN_BASE_SCORE["shark"] == -8

    def test_lookup_resolves_pyharmonics_suffix(self):
        # pyharmonics appends "-<ratio>-<idx>" to pattern names.
        assert _pattern_base_score("gartley-382-1") == 5
        assert _pattern_base_score("crab-1.618-0") == -3
        assert _pattern_base_score("deep crab-1.618-1") == -5

    def test_unknown_pattern_returns_zero(self):
        assert _pattern_base_score("totally-new-shape") == 0

    def test_empty_or_none_returns_zero(self):
        assert _pattern_base_score("") == 0


class TestScoreCandidateAppliesBump:
    def test_gartley_outranks_crab_with_same_input(self):
        df = _make_df()
        ctx = _prepare_score_context(
            df, "15m",
            {"rsi": [{"bullish": True}], "macd": [{"bullish": True}]},
        )
        assert ctx is not None
        sig_gartley = score_candidate(ctx, _candidate("gartley-382-0"))
        sig_crab = score_candidate(ctx, _candidate("crab-1.618-0"))
        assert sig_gartley is not None and sig_crab is not None
        # Gartley (+5) > Crab (-3) → gartley should be the higher-scored signal.
        assert sig_gartley.confluence_score > sig_crab.confluence_score

    def test_width_pct_propagates_to_signal(self):
        df = _make_df()
        ctx = _prepare_score_context(
            df, "15m",
            {"rsi": [{"bullish": True}], "macd": [{"bullish": True}]},
        )
        assert ctx is not None
        sig = score_candidate(ctx, _candidate("gartley"))
        assert sig is not None
        assert sig.width_pct is not None
        assert sig.width_pct >= 0