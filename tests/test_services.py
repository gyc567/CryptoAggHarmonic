"""Tests for service layer: analysis orchestrator."""

from unittest.mock import MagicMock, patch

import pytest

from app.api.errors import AppError
from app.domain.enums import AnalysisType, ErrorCode, Interval, Market, Status
from app.domain.schemas import AnalyzeRequest
from app.services.analysis import AnalysisOrchestrator, _extract_sentiment


class TestExtractSentiment:
    def test_bullish(self):
        assert _extract_sentiment("This is bullish") == "bullish"
        assert _extract_sentiment("BULLISH signal") == "bullish"
        assert _extract_sentiment("看多") == "bullish"

    def test_bearish(self):
        assert _extract_sentiment("This is bearish") == "bearish"
        assert _extract_sentiment("BEARISH trend") == "bearish"
        assert _extract_sentiment("看空") == "bearish"

    def test_neutral(self):
        assert _extract_sentiment("Neutral outlook") == "neutral"
        assert _extract_sentiment("中性") == "neutral"

    def test_empty(self):
        assert _extract_sentiment("") is None
        assert _extract_sentiment(None) is None

    def test_unknown(self):
        assert _extract_sentiment("Some random text") is None


class TestAnalysisOrchestrator:
    @pytest.fixture
    def orchestrator(self):
        return AnalysisOrchestrator()

    @pytest.fixture
    def valid_request(self):
        return AnalyzeRequest(
            market=Market.BINANCE,
            symbol="BTCUSDT",
            interval=Interval.H1,
        )

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_analyze_basic(self, mock_detect, mock_fetch, orchestrator, valid_request):
        mock_fetch.return_value = MagicMock()
        mock_detect.return_value = {
            "position": None,
            "patterns": {},
            "divergences": {},
        }
        result = orchestrator.analyze(valid_request)
        assert result.status == Status.NO_RESULT

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_analyze_with_pattern(
        self, mock_detect, mock_fetch, orchestrator, valid_request
    ):
        mock_fetch.return_value = MagicMock()
        mock_detect.return_value = {
            "position": MagicMock(),
            "patterns": {"family": "XABCD", "direction": "bullish"},
            "divergences": {},
        }
        result = orchestrator.analyze(valid_request)
        assert result.status == Status.COMPLETED
        assert result.technical_result.pattern_family == "XABCD"

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_analyze_forming_type(
        self, mock_detect, mock_fetch, orchestrator
    ):
        req = AnalyzeRequest(
            market=Market.BINANCE,
            symbol="BTCUSDT",
            interval=Interval.H1,
            analysis_type=AnalysisType.FORMING,
        )
        mock_fetch.return_value = MagicMock()
        mock_detect.return_value = {
            "position": None,
            "patterns": {},
            "divergences": {},
        }
        result = orchestrator.analyze(req)
        assert result.analysis_type == AnalysisType.FORMING

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_analyze_yahoo_market(
        self, mock_detect, mock_fetch, orchestrator
    ):
        req = AnalyzeRequest(
            market=Market.YAHOO,
            symbol="AAPL",
            interval=Interval.D1,
        )
        mock_fetch.return_value = MagicMock()
        mock_detect.return_value = {
            "position": None,
            "patterns": {},
            "divergences": {},
        }
        result = orchestrator.analyze(req)
        assert result.market == Market.YAHOO
        assert result.symbol == "AAPL"

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_analyze_formed_type(
        self, mock_detect, mock_fetch, orchestrator
    ):
        req = AnalyzeRequest(
            market=Market.BINANCE,
            symbol="ETHUSDT",
            interval=Interval.H4,
            analysis_type=AnalysisType.FORMED,
        )
        mock_fetch.return_value = MagicMock()
        mock_detect.return_value = {
            "position": None,
            "patterns": {},
            "divergences": {},
        }
        result = orchestrator.analyze(req)
        assert result.analysis_type == AnalysisType.FORMED

    def test_analyze_custom_parameters(self, orchestrator):
        req = AnalyzeRequest(
            market=Market.BINANCE,
            symbol="BTCUSDT",
            interval=Interval.D1,
            limit_to=5,
            percent_complete=0.9,
            candles=2000,
        )
        # Just verify validation passes - parameters are passed to detect_patterns
        assert req.limit_to == 5
        assert req.percent_complete == 0.9
        assert req.candles == 2000
