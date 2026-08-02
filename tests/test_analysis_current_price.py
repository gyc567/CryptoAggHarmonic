"""Tests for current_price surface in /api/analyze responses.

The dashboard's "实时价" cell depends on the orchestrator populating
``technical_result.current_price`` from the most recent candle's close. This
suite pins that contract:

* ``current_price`` and ``current_price_at`` are set on every completed
  analysis (and on the no-result branch, so the dashboard still shows a
  useful price when no pattern was detected).
* The orchestrator is resilient to malformed candle data (empty df, missing
  column, non-positive close) — the field defaults to None instead of
  raising.
* The TechnicalResult schema accepts and validates the new field.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.domain.enums import AnalysisType, Interval, Market, Status
from app.domain.schemas import AnalyzeRequest, TechnicalResult
from app.services.analysis import AnalysisOrchestrator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_cd(rows: list[dict]) -> MagicMock:
    """Build a MagicMock candle-data object with a real pandas DataFrame.

    The orchestrator only touches ``cd.df.iloc[-1]["close"]`` and
    ``cd.df.iloc[-1]["dts"]`` so a minimal frame is enough.
    """
    df = pd.DataFrame(rows)
    cd = MagicMock()
    cd.df = df
    return cd


def _stub_rows(close: float, dts: datetime | None = None) -> list[dict]:
    return [
        {"close": 100.0, "dts": datetime(2026, 8, 2, tzinfo=timezone.utc)},
        {"close": close, "dts": dts or datetime(2026, 8, 2, 4, tzinfo=timezone.utc)},
    ]


@pytest.fixture
def orchestrator() -> AnalysisOrchestrator:
    return AnalysisOrchestrator()


@pytest.fixture
def basic_request() -> AnalyzeRequest:
    return AnalyzeRequest(
        market=Market.BINANCE,
        symbol="BTCUSDT",
        interval=Interval.H4,
        analysis_type=AnalysisType.FORMED,
    )


# ---------------------------------------------------------------------------
# Schema: TechnicalResult accepts the new field
# ---------------------------------------------------------------------------


class TestTechnicalResultSchema:
    def test_current_price_optional(self):
        # Default — no current_price supplied — must remain None so the
        # dashboard's `tech.current_price != null` guard fails closed.
        tr = TechnicalResult()
        assert tr.current_price is None
        assert tr.current_price_at is None

    def test_current_price_positive_only(self):
        # gt=0: zero and negative prices are rejected by the validator.
        # This keeps the dashboard from rendering "实时价: 0" or "实时价: -3"
        # when upstream returns a degenerate frame.
        with pytest.raises(Exception):
            TechnicalResult(current_price=0)
        with pytest.raises(Exception):
            TechnicalResult(current_price=-1.5)

    def test_current_price_round_trip(self):
        tr = TechnicalResult(
            current_price=67500.42,
            current_price_at="2026-08-02T04:00:00+00:00",
        )
        assert tr.current_price == 67500.42
        assert tr.current_price_at == "2026-08-02T04:00:00+00:00"

    def test_current_price_survives_dump(self):
        tr = TechnicalResult(current_price=1234.5, current_price_at="2026-08-02T00:00:00+00:00")
        dumped = tr.model_dump()
        assert dumped["current_price"] == 1234.5
        assert dumped["current_price_at"] == "2026-08-02T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Orchestrator: current_price extraction
# ---------------------------------------------------------------------------


class TestCurrentPriceExtraction:
    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_no_result_path_includes_current_price(
        self, mock_detect, mock_fetch, orchestrator, basic_request
    ):
        """Even when no pattern is found the latest close should appear on
        the response so the dashboard can render the price card."""
        mock_fetch.return_value = _make_cd(_stub_rows(close=67800.0))
        mock_detect.return_value = {
            "position": None,
            "patterns": {},
            "divergences": {},
        }

        result = orchestrator.analyze(basic_request)

        assert result.status == Status.NO_RESULT
        assert result.technical_result.current_price == 67800.0
        assert result.technical_result.current_price_at is not None
        # The ISO timestamp should parse cleanly to a UTC datetime.
        parsed = datetime.fromisoformat(result.technical_result.current_price_at)
        assert parsed.tzinfo is not None

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_completed_path_includes_current_price(
        self, mock_detect, mock_fetch, orchestrator, basic_request
    ):
        """When a pattern is detected the latest close should ride alongside
        the trade levels — the dashboard's realtime price cell depends on it."""
        mock_fetch.return_value = _make_cd(_stub_rows(close=65000.0))
        position = MagicMock()
        position.strike = 64800.0
        position.stop = 63500.0
        position.targets = [66500.0, 68000.0]
        mock_detect.return_value = {
            "position": position,
            "patterns": {"family": "XABCD", "direction": "bullish"},
            "divergences": {},
        }

        result = orchestrator.analyze(basic_request)

        assert result.status == Status.COMPLETED
        assert result.technical_result.current_price == 65000.0
        assert result.technical_result.current_price_at is not None
        # Trade levels from the position are still populated normally — the
        # new field must not collide with the existing extraction logic.
        assert result.technical_result.entry_price == 64800.0
        assert result.technical_result.stop_loss == 63500.0

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_empty_df_does_not_crash(self, mock_detect, mock_fetch, orchestrator, basic_request):
        """An upstream that returns zero rows must not abort the request.
        current_price falls back to None and the rest of the no-result path
        runs as normal."""
        mock_fetch.return_value = _make_cd([])
        mock_detect.return_value = {
            "position": None,
            "patterns": {},
            "divergences": {},
        }

        result = orchestrator.analyze(basic_request)

        assert result.status == Status.NO_RESULT
        assert result.technical_result.current_price is None
        assert result.technical_result.current_price_at is None

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_non_positive_close_ignored(self, mock_detect, mock_fetch, orchestrator, basic_request):
        """A zero or negative close from upstream (degenerate data) must not
        surface as the realtime price. The dashboard's gt=0 validator would
        reject it anyway, but we filter earlier so the rest of the response
        still goes through cleanly."""
        mock_fetch.return_value = _make_cd(_stub_rows(close=0.0))
        mock_detect.return_value = {
            "position": None,
            "patterns": {},
            "divergences": {},
        }

        result = orchestrator.analyze(basic_request)

        assert result.technical_result.current_price is None

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_missing_dts_still_returns_price(
        self, mock_detect, mock_fetch, orchestrator, basic_request
    ):
        """If the candle frame has a close but no dts column, current_price
        should still be populated and only the timestamp should be missing."""
        df = pd.DataFrame([{"close": 123.45}])
        mock_fetch.return_value = MagicMock(df=df)
        mock_detect.return_value = {
            "position": None,
            "patterns": {},
            "divergences": {},
        }

        result = orchestrator.analyze(basic_request)

        assert result.technical_result.current_price == 123.45
        assert result.technical_result.current_price_at is None

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_df_attribute_missing_does_not_crash(
        self, mock_detect, mock_fetch, orchestrator, basic_request
    ):
        """Pathological upstream: returns an object without ``.df``. The
        orchestrator should log a warning and continue with current_price
        left as None, rather than 500'ing the request."""
        broken_cd = MagicMock(spec=[])  # no attributes at all
        mock_fetch.return_value = broken_cd
        mock_detect.return_value = {
            "position": None,
            "patterns": {},
            "divergences": {},
        }

        result = orchestrator.analyze(basic_request)

        assert result.technical_result.current_price is None
        assert result.technical_result.current_price_at is None
