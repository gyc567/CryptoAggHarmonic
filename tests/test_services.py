"""Tests for service layer: chart compression, analysis orchestrator."""

from unittest.mock import MagicMock, patch

import pytest

from app.api.errors import AppError
from app.domain.enums import AnalysisType, ErrorCode, Interval, Market, Status
from app.domain.schemas import AnalyzeRequest
from app.services.analysis import AnalysisOrchestrator, _extract_sentiment
from app.services.chart import compress_chart, estimate_size, validate_chart_size


class TestChartCompression:
    def test_compress_chart_no_pil(self):
        """When PIL is not available, should pass through with estimated metadata."""
        raw_bytes = b"fake_png_data"
        # Mock PIL import failure by patching the module-level import
        import app.services.chart as chart_module

        original_image = getattr(chart_module, "Image", None)
        try:
            chart_module.Image = None  # Simulate PIL not available
            compressed, meta = compress_chart(raw_bytes)
            assert compressed == raw_bytes
            assert meta.format == "png"
            assert meta.width is not None
            assert meta.height is not None
        finally:
            if original_image is not None:
                chart_module.Image = original_image

    def test_compress_chart_with_pil(self):
        """When PIL is available, should resize if too large."""
        try:
            import io

            from PIL import Image
        except ImportError:
            pytest.skip("PIL not available")

        # Create a small test image
        img = Image.new("RGB", (100, 100), color="red")
        output = io.BytesIO()
        img.save(output, format="PNG")
        raw_bytes = output.getvalue()

        compressed, meta = compress_chart(raw_bytes, max_width=50, max_height=50)
        assert meta.width <= 50
        assert meta.height <= 50

    def test_compress_chart_within_bounds(self):
        """Image within bounds should not be resized."""
        try:
            import io

            from PIL import Image
        except ImportError:
            pytest.skip("PIL not available")

        img = Image.new("RGB", (100, 100), color="blue")
        output = io.BytesIO()
        img.save(output, format="PNG")
        raw_bytes = output.getvalue()

        compressed, meta = compress_chart(raw_bytes, max_width=200, max_height=200)
        assert meta.width == 100
        assert meta.height == 100

    def test_estimate_size(self):
        assert estimate_size(b"12345") == 5
        assert estimate_size(b"") == 0

    def test_validate_chart_size_within_limit(self):
        assert validate_chart_size(b"x" * 1000, max_size_bytes=2000) is True

    def test_validate_chart_size_exceeds_limit(self):
        assert validate_chart_size(b"x" * 2000, max_size_bytes=1000) is False

    def test_validate_chart_size_default_limit(self):
        # Default is 1MB
        assert validate_chart_size(b"x" * 500) is True
        assert validate_chart_size(b"x" * 2_000_000) is False


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

    def test_none(self):
        assert _extract_sentiment("") is None
        assert _extract_sentiment(None) is None
        assert _extract_sentiment("Some random text") is None


class TestAnalysisOrchestrator:
    @pytest.fixture
    def orchestrator(self):
        return AnalysisOrchestrator(prompt_context={})

    @pytest.fixture
    def valid_request(self):
        return AnalyzeRequest(
            market=Market.BINANCE,
            symbol="BTCUSDT",
            interval=Interval.D1,
        )

    def test_analyze_invalid_symbol(self, orchestrator):
        # Pydantic catches empty string before validator, so test with invalid chars
        req = AnalyzeRequest(
            market=Market.BINANCE,
            symbol="INVALID-SYMBOL",
            interval=Interval.D1,
        )
        with pytest.raises(AppError) as exc_info:
            orchestrator.analyze(req)
        assert exc_info.value.code == ErrorCode.INVALID_PARAMS

    def test_analyze_invalid_interval(self, orchestrator):
        # Manually test validator path
        with pytest.raises(AppError):
            from app.domain.validators import validate_interval

            validate_interval("invalid")

    @patch("app.services.analysis.fetch_market_data")
    def test_analyze_market_data_failure(self, mock_fetch, orchestrator, valid_request):
        mock_fetch.side_effect = AppError(
            ErrorCode.MARKET_DATA_UNAVAILABLE,
            "Market data unavailable",
        )
        with pytest.raises(AppError) as exc_info:
            orchestrator.analyze(valid_request)
        assert exc_info.value.code == ErrorCode.MARKET_DATA_UNAVAILABLE

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_analyze_no_patterns(self, mock_detect, mock_fetch, orchestrator, valid_request):
        mock_fetch.return_value = MagicMock()
        mock_detect.return_value = {
            "position": None,
            "patterns": {},
            "divergences": {},
        }

        result = orchestrator.analyze(valid_request)
        assert result.status == Status.NO_RESULT
        assert result.symbol == "BTCUSDT"
        assert result.market == Market.BINANCE

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_analyze_with_patterns(self, mock_detect, mock_fetch, orchestrator, valid_request):
        mock_fetch.return_value = MagicMock()
        mock_position = MagicMock()
        mock_position.strike = 100.0
        mock_position.stop = 95.0
        mock_position.targets = [110.0, 120.0]

        mock_detect.return_value = {
            "position": mock_position,
            "patterns": {"family": "XABCD"},
            "divergences": {},
        }

        result = orchestrator.analyze(valid_request)
        assert result.status == Status.COMPLETED
        assert result.technical_result.pattern_family == "XABCD"
        # Without a validated signal the adapter surfaces the raw Position.
        assert result.technical_result.entry_price == 100.0
        assert result.technical_result.stop_loss == 95.0
        assert result.technical_result.target_price == 110.0
        assert result.technical_result.confidence == "raw-position"

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    @patch("app.services.analysis._generate_interpretation")
    def test_analyze_interpretation_failure_continues(self, mock_interp, mock_detect, mock_fetch, orchestrator, valid_request):
        mock_fetch.return_value = MagicMock()
        mock_position = MagicMock()
        mock_position.strike = 100.0
        mock_detect.return_value = {
            "position": mock_position,
            "patterns": {"family": "XABCD"},
            "divergences": {},
        }
        mock_interp.side_effect = AppError(
            ErrorCode.MODEL_ERROR,
            "Model failed",
        )

        result = orchestrator.analyze(valid_request)
        assert result.status == Status.COMPLETED
        # When interpretation fails with MODEL_ERROR, the fallback message is set
        assert result.interpretation.summary is not None or result.interpretation.raw_response is None

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_analyze_chart_failure_continues(self, mock_detect, mock_fetch, orchestrator, valid_request):
        mock_fetch.return_value = MagicMock()
        mock_position = MagicMock()
        mock_position.strike = 100.0

        mock_plot = MagicMock()
        mock_plot.to_image.side_effect = Exception("Chart failed")

        mock_detect.return_value = {
            "position": mock_position,
            "patterns": {"family": "XABCD"},
            "divergences": {},
            "plot": mock_plot,
        }

        result = orchestrator.analyze(valid_request)
        assert result.status == Status.COMPLETED
        # Chart may be empty but analysis succeeds
        assert result.chart is not None

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_analyze_chart_success_and_distributed(self, mock_detect, mock_fetch, orchestrator, valid_request):
        """Single render success -> chart carries the distributed URL."""
        from app.domain.schemas import ChartMeta

        mock_fetch.return_value = MagicMock()
        mock_detect.return_value = {
            "position": MagicMock(),
            "patterns": {"family": "XABCD"},
            "divergences": {},
            "plot": MagicMock(),
        }
        fake_meta = ChartMeta(format="png", width=600, height=300)
        with (
            patch("app.services.analysis.render_chart", return_value=(b"\x89PNG\x00" * 8, fake_meta)),
            patch("app.services.analysis.save_chart_locally", return_value="instance/charts/x.png"),
        ):
            result = orchestrator.analyze(valid_request)
        assert result.status == Status.COMPLETED
        assert result.chart.width == 600
        assert result.chart.url is not None
        assert result.chart.url.startswith("/api/charts/")

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_analyze_chart_oversize_omitted(self, mock_detect, mock_fetch, orchestrator, valid_request):
        """Chart beyond the size cap is dropped but analysis succeeds."""
        from app.domain.schemas import ChartMeta

        mock_fetch.return_value = MagicMock()
        mock_detect.return_value = {
            "position": MagicMock(),
            "patterns": {"family": "XABCD"},
            "divergences": {},
            "plot": MagicMock(),
        }
        fake_meta = ChartMeta(format="png", width=600, height=300)
        with (
            patch("app.services.analysis.render_chart", return_value=(b"\x89PNG\x00" * 8, fake_meta)),
            patch("app.services.analysis.validate_chart_size", return_value=False),
        ):
            result = orchestrator.analyze(valid_request)
        assert result.status == Status.COMPLETED
        assert result.chart.url is None

    @patch("app.services.analysis.fetch_market_data")
    @patch("app.services.analysis.detect_patterns")
    def test_analyze_yahoo_market(self, mock_detect, mock_fetch, orchestrator):
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
    def test_analyze_formed_type(self, mock_detect, mock_fetch, orchestrator):
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
