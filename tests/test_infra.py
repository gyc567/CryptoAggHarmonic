"""Tests for infrastructure layer: pyharmonics adapter."""

from unittest.mock import MagicMock, patch

import pytest

from app.api.errors import AppError
from app.domain.enums import ErrorCode, Interval, Market
from app.domain.schemas import TechnicalResult
from app.infra.pyharmonics_adapter import (
    detect_patterns,
    fetch_market_data,
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
    """Pattern detection tests - basic functionality."""

    def test_detect_patterns_function_exists(self):
        """Verify detect_patterns function exists and is callable."""
        from app.infra.pyharmonics_adapter import detect_patterns
        assert callable(detect_patterns)

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
        # risk_reward_ratio is computed by net_rr() which deducts fees
        assert result.risk_reward_ratio == pytest.approx(1.83, abs=0.01)
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
        # risk_reward_ratio is computed by net_rr() which deducts fees
        assert result.risk_reward_ratio == pytest.approx(1.83, abs=0.01)
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
