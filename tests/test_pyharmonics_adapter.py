"""Unit tests for the v2 forming view in app.services.analysis.

These tests stub out the heavy pieces (fetch_market_data, detect_patterns,
openai_handler, supabase uploads) and feed hand-crafted detection results
through ``AnalysisOrchestrator._build_forming_view`` and the full
``analyze()`` path.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.domain.enums import AnalysisType, Interval, Market, Status
from app.domain.schemas import AnalyzeRequest, ChartMeta
from app.infra.analysis_cache import AnalysisCache
from app.services.analysis import AnalysisOrchestrator


def _make_df(n: int = 600) -> pd.DataFrame:
    closes = [100.0 + i * 0.2 for i in range(n)]
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
    return df


def _make_request(analysis_type: AnalysisType = AnalysisType.FORMING) -> AnalyzeRequest:
    return AnalyzeRequest(
        market=Market.BINANCE,
        symbol="BTCUSDT",
        interval=Interval.H4,
        analysis_type=analysis_type,
        limit_to=5,
        percent_complete=0.8,
        candles=600,
    )


def _candle_data() -> SimpleNamespace:
    return SimpleNamespace(
        df=_make_df(),
        symbol="BTCUSDT",
        interval=Interval.H4,
    )


class _Pattern:
    """Lightweight stand-in for a pyharmonics pattern object.

    ``extract_candidates`` reads ``.y``, ``.x``, ``.name``,
    ``.completion_min_price``, ``.completion_max_price``, ``.bullish``.
    """

    def __init__(self, name, y, completion_min, completion_max, bullish=True,
                 x=None):
        self.name = name
        self.y = y
        self.completion_min_price = completion_min
        self.completion_max_price = completion_max
        self.bullish = bullish
        self.x = x if x is not None else [0, 10, 20, 580, 599]


def _detection_result(forming_patterns=None, formed_patterns=None,
                      position=None) -> dict:
    """Build a detection_result dict shaped as ``extract_candidates`` expects."""
    return {
        "divergences": {},
        "patterns": {},
        "position": position,
        "plot": None,
        "raw_assessment": {
            "forming": {"XABCD": forming_patterns or []},
            "patterns": {"XABCD": formed_patterns or []},
        },
    }


# A PRZ safely above the last close (220) so no bar wicks into it.
_FAR_PRZ = (225.0, 230.0)


class TestBuildFormingView:
    def test_returns_only_forming_candidates(self):
        formed = _Pattern(
            "crab-1.618-0", [95.0, 110.0, 100.0, 107.0, 103.0],
            *_FAR_PRZ, bullish=True,
        )
        forming = _Pattern(
            "gartley-382-0", [95.0, 110.0, 100.0, 107.0, 103.0],
            *_FAR_PRZ, bullish=True,
        )
        det = _detection_result(forming_patterns=[forming],
                                formed_patterns=[formed])
        orch = AnalysisOrchestrator(cache=AnalysisCache(redis_url=""))
        out = orch._build_forming_view(_candle_data(), det)
        assert len(out) == 1
        assert out[0].candidate.name == "gartley-382-0"
        assert out[0].candidate.formed is False

    def test_past_tp2_candidate_dropped(self):
        # Bullish gartley A=110, D=102 → TP2=106.94. Last close=220 → past.
        forming = _Pattern(
            "gartley-382-0", [95.0, 110.0, 100.0, 107.0, 102.0],
            102.0, 104.0, bullish=True,
        )
        det = _detection_result(forming_patterns=[forming])
        orch = AnalysisOrchestrator(cache=AnalysisCache(redis_url=""))
        out = orch._build_forming_view(_candle_data(), det)
        assert out == []

    def test_sort_tradable_first_then_closest(self):
        # Two forming candidates both tradable, sort by dist_pct: closer first.
        near = _Pattern(
            "bat-382-0", [95.0, 110.0, 100.0, 107.0, 103.0],
            221.0, 222.0, bullish=True,
        )
        far = _Pattern(
            "crab-1.618-0", [95.0, 110.0, 100.0, 107.0, 103.0],
            400.0, 410.0, bullish=True,
        )
        det = _detection_result(forming_patterns=[far, near])
        orch = AnalysisOrchestrator(cache=AnalysisCache(redis_url=""))
        out = orch._build_forming_view(_candle_data(), det)
        assert len(out) == 2
        assert out[0].candidate.name == "bat-382-0"
        assert out[0].metrics.dist_pct < out[1].metrics.dist_pct

    def test_macro_overlay_attached(self):
        forming = _Pattern(
            "gartley-382-0", [95.0, 110.0, 100.0, 107.0, 103.0],
            *_FAR_PRZ, bullish=True,
        )
        det = _detection_result(forming_patterns=[forming])
        orch = AnalysisOrchestrator(cache=AnalysisCache(redis_url=""))
        out = orch._build_forming_view(_candle_data(), det)
        assert len(out) == 1
        assert out[0].macro is not None
        assert out[0].macro.size_mult > 0
        # No daily series passed → macro layer falls back to 0.8 conservative.
        assert out[0].macro.size_mult == 0.8

    def test_exception_does_not_propagate(self):
        # Passing a non-dict detection result triggers the except branch.
        orch = AnalysisOrchestrator(cache=AnalysisCache(redis_url=""))
        out = orch._build_forming_view(_candle_data(), {"raw_assessment": None})
        assert out == []


class TestFormingCandidatesInResponse:
    @patch("app.services.analysis.upload_chart", return_value=None)
    @patch("app.services.analysis.save_chart_locally", return_value="/tmp/x.png")
    @patch("app.services.analysis.render_chart",
           return_value=(b"png-bytes", ChartMeta(format="png", width=600, height=300)))
    @patch("app.services.analysis.fetch_market_data", return_value=_candle_data())
    @patch("app.services.analysis.detect_patterns")
    def test_forming_candidates_populated(
        self, mock_detect, _fetch, _render, _local, _upload,
    ):
        forming = _Pattern(
            "gartley-382-0", [95.0, 110.0, 100.0, 107.0, 103.0],
            221.0, 222.0, bullish=True,
        )
        mock_detect.return_value = _detection_result(
            forming_patterns=[forming],
            position=SimpleNamespace(side="long"),
        )

        orch = AnalysisOrchestrator(cache=AnalysisCache(redis_url=""))
        data = orch.analyze(_make_request(AnalysisType.FORMING))
        assert data.status == Status.COMPLETED
        assert len(data.forming_candidates) == 1
        assert data.forming_candidates[0]["pattern_name"] == "gartley-382-0"
        assert "macro" in data.forming_candidates[0]
        assert "width_pct" in data.forming_candidates[0]
        assert "tradable" in data.forming_candidates[0]
