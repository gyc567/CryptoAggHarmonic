"""Tests for infrastructure layer: pyharmonics adapter."""

from unittest.mock import MagicMock, patch

import pytest

from app.api.errors import AppError
from app.domain.enums import ErrorCode, Interval, Market
from app.domain.schemas import TechnicalResult
from app.infra.pyharmonics_adapter import (
    detect_patterns,
    fetch_market_data,
    render_chart,
    technical_result_to_schema,
)


class TestFetchMarketData:
    @patch("app.infra.pyharmonics_adapter.DirectBinanceCandleData")
    def test_fetch_binance_success(self, mock_cls):
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        result = fetch_market_data(
            Market.BINANCE,
            "BTCUSDT",
            Interval.D1,
            candles=1000,
        )
        mock_instance.get_candles.assert_called_once_with("BTCUSDT", "1d", 1000)
        assert result == mock_instance

    @patch("app.infra.pyharmonics_adapter.YahooCandleData")
    def test_fetch_yahoo_success(self, mock_cls):
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        result = fetch_market_data(
            Market.YAHOO,
            "AAPL",
            Interval.D1,
            candles=500,
        )
        mock_instance.get_candles.assert_called_once_with("AAPL", "1d", 500)
        assert result == mock_instance

    @patch("app.infra.pyharmonics_adapter.DirectBinanceCandleData")
    def test_fetch_binance_failure(self, mock_cls):
        mock_cls.side_effect = Exception("Network error")

        with pytest.raises(AppError) as exc_info:
            fetch_market_data(Market.BINANCE, "BTCUSDT", Interval.D1)

        assert exc_info.value.code == ErrorCode.MARKET_DATA_UNAVAILABLE
        assert "暂时无法获取" in exc_info.value.message
        assert exc_info.value.retryable is True

    @patch("app.infra.pyharmonics_adapter.YahooCandleData")
    def test_fetch_yahoo_failure(self, mock_cls):
        mock_cls.side_effect = Exception("Timeout")

        with pytest.raises(AppError) as exc_info:
            fetch_market_data(Market.YAHOO, "AAPL", Interval.D1)

        assert exc_info.value.code == ErrorCode.MARKET_DATA_UNAVAILABLE

    def test_fetch_unsupported_market(self):
        with pytest.raises((AppError, ValueError)):
            fetch_market_data(Market("unsupported"), "BTCUSDT", Interval.D1)


class TestDetectPatterns:
    def test_detect_no_patterns(self):
        with (
            patch("app.infra.pyharmonics_adapter.OHLCTechnicals") as mock_tech_cls,
            patch("app.infra.pyharmonics_adapter.HarmonicSearch") as mock_hs_cls,
            patch("app.infra.pyharmonics_adapter.DivergenceSearch") as mock_div_cls,
            patch("app.infra.pyharmonics_adapter.HarmonicPlotter") as mock_plotter_cls,
        ):
            mock_candle = MagicMock()
            mock_candle.df = MagicMock()
            mock_candle.symbol = "BTCUSDT"
            mock_candle.interval = "1d"

            mock_tech = MagicMock()
            mock_tech_cls.return_value = mock_tech

            mock_hs = MagicMock()
            mock_hs.XABCD = "XABCD"
            mock_hs.ABCD = "ABCD"
            mock_hs.ABC = "ABC"
            mock_hs.get_patterns.return_value = {
                "XABCD": [],
                "ABCD": [],
                "ABC": [],
            }
            mock_hs_cls.return_value = mock_hs

            mock_div = MagicMock()
            mock_div.get_patterns.return_value = {}
            mock_div_cls.return_value = mock_div

            mock_plot = MagicMock()
            mock_plotter_cls.return_value = mock_plot

            result = detect_patterns(mock_candle, limit_to=10, percent_complete=0.8)

            assert result["position"] is None
            assert result["patterns"] == {}
            assert result["divergences"] == {}

    def test_detect_with_pattern(self):
        with (
            patch("app.infra.pyharmonics_adapter.OHLCTechnicals") as mock_tech_cls,
            patch("app.infra.pyharmonics_adapter.HarmonicSearch") as mock_hs_cls,
            patch("app.infra.pyharmonics_adapter.DivergenceSearch") as mock_div_cls,
            patch("app.infra.pyharmonics_adapter.HarmonicPlotter") as mock_plotter_cls,
            patch("app.infra.pyharmonics_adapter.Position") as mock_pos_cls,
            patch("app.infra.pyharmonics_adapter.PositionPlotter") as mock_pos_plot_cls,
        ):
            mock_candle = MagicMock()
            mock_candle.df = MagicMock()
            mock_candle.symbol = "BTCUSDT"
            mock_candle.interval = "1d"

            mock_tech = MagicMock()
            mock_tech_cls.return_value = mock_tech

            mock_pattern = MagicMock()
            mock_pattern.completion_min_price = 90.0
            mock_pattern.completion_max_price = 110.0
            mock_pattern.direction = "long"

            mock_hs = MagicMock()
            mock_hs.XABCD = "XABCD"
            mock_hs.ABCD = "ABCD"
            mock_hs.ABC = "ABC"
            mock_hs.get_patterns.side_effect = lambda formed=None, family=None: (
                {
                    "XABCD": [mock_pattern] if family == "XABCD" else [],
                    "ABCD": [],
                    "ABC": [],
                }
                if family
                else {
                    "XABCD": [mock_pattern],
                    "ABCD": [],
                    "ABC": [],
                }
            )
            mock_hs_cls.return_value = mock_hs

            mock_div = MagicMock()
            mock_div.get_patterns.return_value = {}
            mock_div_cls.return_value = mock_div

            mock_plot = MagicMock()
            mock_plotter_cls.return_value = mock_plot

            mock_position = MagicMock()
            mock_pos_cls.return_value = mock_position

            mock_pos_plot = MagicMock()
            mock_pos_plot_cls.return_value = mock_pos_plot

            result = detect_patterns(mock_candle, limit_to=10, percent_complete=0.8)

            assert result["position"] is not None
            assert result["patterns"]["family"] == "XABCD"
            assert result["patterns"]["direction"] == "long"

    def test_detect_patterns_error(self):
        mock_candle = MagicMock()
        mock_candle.df = MagicMock()

        with patch("app.infra.pyharmonics_adapter.OHLCTechnicals") as mock_tech:
            mock_tech.side_effect = Exception("Technical error")
            with pytest.raises(AppError) as exc_info:
                detect_patterns(mock_candle)
            assert exc_info.value.code == ErrorCode.INTERNAL_ERROR


class TestGenerateChart:
    """Chart rendering via render_chart (single-pass, plotly-sanitized)."""

    # Minimal fake PNG payload (header + filler); compress_chart falls back
    # to pass-through when PIL is unavailable, so no real image is needed.
    _PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

    def test_generate_with_plot(self):
        mock_plot = MagicMock()
        with (
            patch("plotly.io.to_json", return_value="{}"),
            patch("plotly.io.from_json", return_value=MagicMock()),
            patch("plotly.io.to_image", return_value=self._PNG),
        ):
            image_bytes, meta = render_chart({"plot": mock_plot})
        assert meta.format == "png"
        assert meta.width is not None
        assert meta.height is not None
        assert image_bytes.startswith(b"\x89PNG")

    def test_generate_with_fallback(self):
        mock_plot = MagicMock()
        with (
            patch("plotly.io.to_json", return_value="{}"),
            patch("plotly.io.from_json", return_value=MagicMock()),
            patch("plotly.io.to_image", return_value=self._PNG),
        ):
            _, meta = render_chart({"plot_fallback": mock_plot})
        assert meta.format == "png"

    def test_generate_no_plot(self):
        with pytest.raises(AppError) as exc_info:
            render_chart({})
        assert exc_info.value.code == ErrorCode.CHART_ERROR

    def test_generate_empty_image(self):
        mock_plot = MagicMock()
        with (
            patch("plotly.io.to_json", return_value="{}"),
            patch("plotly.io.from_json", return_value=MagicMock()),
            patch("plotly.io.to_image", return_value=b""),
        ):
            with pytest.raises(AppError) as exc_info:
                render_chart({"plot": mock_plot})
        assert exc_info.value.code == ErrorCode.CHART_ERROR

    def test_generate_exception(self):
        mock_plot = MagicMock()
        mock_plot.main_plot.to_json.side_effect = Exception("Render error")

        with pytest.raises(AppError) as exc_info:
            render_chart({"plot": mock_plot})
        assert exc_info.value.code == ErrorCode.CHART_ERROR
        assert "图表生成失败" in exc_info.value.message


class TestTechnicalResultToSchema:
    def test_empty_result(self):
        result = technical_result_to_schema({})
        assert isinstance(result, TechnicalResult)
        assert result.pattern_family is None

    def test_with_pattern_no_position(self):
        result = technical_result_to_schema(
            {
                "patterns": {"family": "ABCD"},
                "divergences": {},
            }
        )
        assert result.pattern_family == "ABCD"
        assert result.pattern_type == "formed"
        assert result.entry_price is None

    def test_with_forming_pattern(self):
        result = technical_result_to_schema(
            {
                "patterns": {"family": "XABCD", "forming": True},
                "divergences": {},
            }
        )
        assert result.pattern_family == "XABCD"
        assert result.pattern_type == "forming"

    def test_with_position(self):
        # Without a validated signal, the adapter falls back to the raw
        # pyharmonics Position so the UI still shows actionable levels.
        # Confidence is flagged so consumers know these are unvalidated.
        mock_position = MagicMock()
        mock_position.strike = 100.0
        mock_position.stop = 95.0
        mock_position.targets = [110.0, 120.0]

        result = technical_result_to_schema(
            {
                "patterns": {"family": "XABCD"},
                "position": mock_position,
                "divergences": {},
            }
        )
        assert result.entry_price == 100.0
        assert result.stop_loss == 95.0
        assert result.target_price == 110.0
        assert result.risk_reward_ratio == 2.0
        assert result.confidence == "raw-position"

    @staticmethod
    def _signal_dict(**overrides):
        base = {
            "status": "confirmed",
            "grade": "A",
            "direction": "long",
            "pattern_name": "gartley",
            "family": "XABCD",
            "formed": True,
            "entry_zone": [95.0, 105.0],
            "entry_reference": 100.0,
            "stop_loss": 95.0,
            "targets": [{"label": "TP1", "price": 110.0}, {"label": "TP2", "price": 120.0}],
            "net_rr_tp2": 2.0,
        }
        base.update(overrides)
        return base

    def test_with_signal_derives_legacy_fields(self):
        # v4 unified contract: legacy fields mirror the validated signal.
        result = technical_result_to_schema(
            {"patterns": {"family": "XABCD"}, "divergences": {}},
            signal=self._signal_dict(),
        )
        assert result.entry_price == 100.0
        assert result.stop_loss == 95.0
        assert result.target_price == 110.0
        assert result.risk_reward_ratio == 2.0
        assert result.signal is not None
        assert result.confidence == "validated-signal"

    def test_with_signal_no_targets(self):
        result = technical_result_to_schema(
            {"patterns": {}, "divergences": {}},
            signal=self._signal_dict(targets=[], net_rr_tp2=None),
        )
        assert result.target_price is None
        assert result.risk_reward_ratio is None

    def test_with_divergences(self):
        result = technical_result_to_schema(
            {
                "patterns": {},
                "divergences": {"macd": [{"type": "bullish"}]},
            }
        )
        assert result.divergences == {"macd": [{"type": "bullish"}]}
