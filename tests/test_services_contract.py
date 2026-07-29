"""Contract tests for app/services/{discipline_filters,macro_bias,signal_engine}.

Layer 2 of the three-layer defense: every public function added in this
sprint carries ``@require`` preconditions. These tests pin those contracts so
a future refactor that loosens an invariant has to consciously update the
test, not silently allow bad inputs through.

Pattern mirrors ``test_signals_contract.py`` / ``test_schemas_contract.py``:
one test per precondition, plus a few "documents the intentional non-contract"
tests where a precondition was considered and rejected (e.g. compute_atr's
fallback branch when the rolling window is all-NaN).
"""
from __future__ import annotations

import pandas as pd
import pytest
from icontract import ViolationError

from app.domain.forming_schemas import CandidateMetrics
from app.domain.signals import Candidate
from app.services.discipline_filters import evaluate as discipline_evaluate
from app.services.macro_bias import compute as macro_compute
from app.services.signal_engine import (
    build_signal,
    compute_atr,
    compute_rsi,
    confluence_score,
    extract_candidates,
    htf_trend,
    score_candidate,
)
from tests.test_signal_engine import gartley_candidate  # noqa: E402


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_df(rows: int = 250) -> pd.DataFrame:
    """Minimal DataFrame with high/low/close/volume/open columns."""
    base = 100.0
    return pd.DataFrame({
        "open": [base + i * 0.1 for i in range(rows)],
        "high": [base + i * 0.1 + 0.5 for i in range(rows)],
        "low": [base + i * 0.1 - 1 for i in range(rows)],
        "close": [base + i * 0.1 for i in range(rows)],
        "volume": [1000.0 for _ in range(rows)],
    })


# ---------------------------------------------------------------------------
# discipline_filters.evaluate
# ---------------------------------------------------------------------------


class TestEvaluateRequires:
    @pytest.fixture
    def cand(self):
        return gartley_candidate()

    @pytest.fixture
    def df(self):
        return _make_df(250)

    def test_empty_df_rejected(self, cand):
        with pytest.raises(ViolationError):
            discipline_evaluate(pd.DataFrame(), cand, current_price=100.0)

    def test_zero_prz_low_rejected(self, cand, df):
        # Build a candidate with prz_low = 0 (illegal).
        bad = Candidate(
            family=cand.family,
            name=cand.name,
            bullish=cand.bullish,
            formed=cand.formed,
            points=cand.points,
            completion_min=0.0,
            completion_max=cand.completion_max,
            times=cand.times,
            indices=cand.indices,
        )
        with pytest.raises(ViolationError):
            discipline_evaluate(df, bad, current_price=100.0)

    def test_zero_current_price_rejected(self, cand, df):
        with pytest.raises(ViolationError):
            discipline_evaluate(df, cand, current_price=0.0)

    def test_negative_current_price_rejected(self, cand, df):
        with pytest.raises(ViolationError):
            discipline_evaluate(df, cand, current_price=-10.0)

    def test_negative_max_ttl_rejected(self, cand, df):
        with pytest.raises(ViolationError):
            discipline_evaluate(df, cand, current_price=100.0, max_ttl=-1)

    def test_zero_max_ttl_allowed(self, cand, df):
        """Zero TTL is a legal "everything is stale" configuration."""
        result = discipline_evaluate(df, cand, current_price=100.0, max_ttl=0)
        assert isinstance(result.metrics, CandidateMetrics)
        # At max_ttl=0 every bars_since_c > 0 is "stale".
        assert result.metrics.stale is True

    def test_valid_inputs_pass(self, cand, df):
        result = discipline_evaluate(df, cand, current_price=100.0)
        assert result.metrics.bars_since_c >= 0


# ---------------------------------------------------------------------------
# macro_bias.compute
# ---------------------------------------------------------------------------


class TestMacroComputeRequires:
    @pytest.fixture
    def daily_close(self):
        """Plausible daily series long enough to skip the short-data path."""
        n = 250
        return pd.Series(
            [100.0 + i * 0.5 for i in range(n)],
            index=pd.date_range("2023-01-01", periods=n, freq="D"),
        )

    def test_signal_dir_too_high_rejected(self, daily_close):
        with pytest.raises(ViolationError):
            macro_compute(daily_close, signal_dir=2)

    def test_signal_dir_too_low_rejected(self, daily_close):
        with pytest.raises(ViolationError):
            macro_compute(daily_close, signal_dir=-5)

    def test_signal_dir_zero_allowed(self, daily_close):
        """0 is the documented "no direction" sentinel."""
        overlay = macro_compute(daily_close, signal_dir=0)
        assert overlay is not None

    def test_long_signal_with_long_data_returns_overlay(self, daily_close):
        overlay = macro_compute(daily_close, signal_dir=1)
        assert overlay.size_mult > 0
        assert overlay.macro_dir in ("牛市(价>EMA200)", "熊市(价<EMA200)")

    def test_short_data_returns_conservative_mult(self):
        """Documented intentional non-contract: short data → 0.8 multiplier."""
        overlay = macro_compute(pd.Series([100.0]), signal_dir=1)
        assert overlay.size_mult == 0.8

    def test_none_close_returns_conservative_mult(self):
        """Documented intentional non-contract: None → 0.8 multiplier."""
        overlay = macro_compute(None, signal_dir=1)
        assert overlay.size_mult == 0.8


# ---------------------------------------------------------------------------
# signal_engine.compute_atr
# ---------------------------------------------------------------------------


class TestComputeAtrRequires:
    def test_too_short_df_rejected(self):
        df = _make_df(rows=1)  # only one bar → shift gives NaN, len < 2
        with pytest.raises(ViolationError):
            compute_atr(df)

    def test_zero_window_rejected(self):
        df = _make_df(250)
        with pytest.raises(ViolationError):
            compute_atr(df, window=0)

    def test_missing_columns_rejected(self):
        df = pd.DataFrame({"price": [1.0, 2.0, 3.0]})
        with pytest.raises(ViolationError):
            compute_atr(df)

    def test_valid_df_returns_positive(self):
        atr = compute_atr(_make_df(250))
        assert atr > 0


# ---------------------------------------------------------------------------
# signal_engine.extract_candidates
# ---------------------------------------------------------------------------


class TestExtractCandidatesRequires:
    def test_non_dict_rejected(self):
        with pytest.raises(ViolationError):
            extract_candidates("not a dict")  # type: ignore[arg-type]

    def test_empty_dict_returns_empty(self):
        assert extract_candidates({}) == []

    def test_dict_without_assessment_returns_empty(self):
        assert extract_candidates({"foo": "bar"}) == []


# ---------------------------------------------------------------------------
# signal_engine.build_signal
# ---------------------------------------------------------------------------


class TestBuildSignalRequires:
    @pytest.fixture
    def df(self):
        return _make_df(250)

    def test_empty_interval_rejected(self, df):
        cand = gartley_candidate()
        with pytest.raises(ViolationError):
            build_signal(df, interval="", candidates=[cand])

    def test_invalid_stop_level_rejected(self, df):
        cand = gartley_candidate()
        with pytest.raises(ViolationError):
            build_signal(df, interval="15m", candidates=[cand], stop_level="nope")

    def test_too_short_df_returns_none_not_raises(self, df):
        """Documented intentional non-contract: short df returns None, no error."""
        cand = gartley_candidate()
        assert build_signal(df.iloc[:5], interval="15m", candidates=[cand]) is None

    def test_empty_candidates_returns_none(self, df):
        assert build_signal(df, interval="15m", candidates=[]) is None


# ---------------------------------------------------------------------------
# signal_engine.compute_rsi
# ---------------------------------------------------------------------------


class TestComputeRsiRequires:
    def test_zero_window_rejected(self):
        s = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0])
        with pytest.raises(ViolationError):
            compute_rsi(s, window=0)

    def test_valid_series_returns_value(self):
        s = pd.Series([100.0 + i for i in range(30)])
        v = compute_rsi(s)
        assert 0.0 <= v <= 100.0


# ---------------------------------------------------------------------------
# signal_engine.htf_trend
# ---------------------------------------------------------------------------


class TestHtfTrendRequires:
    def test_empty_interval_rejected(self):
        with pytest.raises(ViolationError):
            htf_trend(pd.DataFrame(), interval="")


# ---------------------------------------------------------------------------
# signal_engine.confluence_score
# ---------------------------------------------------------------------------


class TestConfluenceScoreRequires:
    @pytest.fixture
    def df(self):
        return _make_df(250)

    def test_negative_atr_rejected(self, df):
        cand = gartley_candidate()
        with pytest.raises(ViolationError):
            confluence_score(df, cand, atr=-1.0, rsi=50.0, trend="unknown",
                             divergences={})

    def test_rsi_above_100_rejected(self, df):
        cand = gartley_candidate()
        with pytest.raises(ViolationError):
            confluence_score(df, cand, atr=1.0, rsi=150.0, trend="unknown",
                             divergences={})

    def test_rsi_below_zero_rejected(self, df):
        cand = gartley_candidate()
        with pytest.raises(ViolationError):
            confluence_score(df, cand, atr=1.0, rsi=-5.0, trend="unknown",
                             divergences={})

    def test_unknown_trend_rejected(self, df):
        cand = gartley_candidate()
        with pytest.raises(ViolationError):
            confluence_score(df, cand, atr=1.0, rsi=50.0, trend="sideways",
                             divergences={})

    def test_pa_scale_too_high_rejected(self, df):
        cand = gartley_candidate()
        with pytest.raises(ViolationError):
            confluence_score(df, cand, atr=1.0, rsi=50.0, trend="unknown",
                             divergences={}, pa_scale=5.0)

    def test_missing_close_column_rejected(self, df):
        no_close = df.drop(columns=["close"])
        cand = gartley_candidate()
        with pytest.raises(ViolationError):
            confluence_score(no_close, cand, atr=1.0, rsi=50.0,
                             trend="unknown", divergences={})

    def test_valid_inputs_return_score(self, df):
        cand = gartley_candidate()
        score, factors = confluence_score(
            df, cand, atr=1.0, rsi=50.0, trend="unknown", divergences={},
        )
        assert isinstance(score, (int, float))
        assert isinstance(factors, dict)


# ---------------------------------------------------------------------------
# signal_engine.score_candidate
# ---------------------------------------------------------------------------


class TestScoreCandidateRequires:
    def test_invalid_stop_level_rejected(self):
        """If a caller passes a bad stop_level it should fail fast."""
        from app.services.signal_engine import _prepare_score_context
        df = _make_df(250)
        ctx = _prepare_score_context(df, "15m", None)
        assert ctx is not None
        cand = gartley_candidate()
        with pytest.raises(ViolationError):
            score_candidate(ctx, cand, stop_level="extreme")