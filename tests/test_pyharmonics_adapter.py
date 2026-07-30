"""Unit tests for the v2 forming view in app.services.analysis.

These tests stub out the heavy pieces (fetch_market_data, detect_patterns,
openai_handler, supabase uploads) and feed hand-crafted detection results
through ``AnalysisOrchestrator._build_forming_view`` and the full
``analyze()`` path.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from app.domain.enums import AnalysisType, Interval, Market, Status
from app.domain.schemas import AnalyzeRequest
from app.infra.analysis_cache import AnalysisCache
from app.services.analysis import AnalysisOrchestrator


def _make_df(n: int = 600) -> pd.DataFrame:
    closes = [100.0 + i * 0.2 for i in range(n)]
    rows = []
    for i, c in enumerate(closes):
        rows.append(
            {
                "open": c,
                "high": c + 0.5,
                "low": c - 0.5,
                "close": c,
                "volume": 100.0,
                "close_time": 1_700_000_000 + i * 900,
            }
        )
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

    def __init__(self, name, y, completion_min, completion_max, bullish=True, x=None):
        self.name = name
        self.y = y
        self.completion_min_price = completion_min
        self.completion_max_price = completion_max
        self.bullish = bullish
        self.x = x if x is not None else [0, 10, 20, 580, 599]


def _detection_result(forming_patterns=None, formed_patterns=None, position=None) -> dict:
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


