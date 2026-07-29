"""Tests for domain layer: enums, schemas, validators."""

import pytest
from pydantic import ValidationError

from app.api.errors import AppError
from app.api.errors import ErrorCode as AppErrorCode
from app.domain.enums import AnalysisType, ErrorCode, Interval, Market, Status
from app.domain.schemas import (
    AnalysisData,
    AnalyzeRequest,
    ChartMeta,
    ErrorResponse,
    HealthResponse,
    Interpretation,
    MarketsResponse,
    SuccessResponse,
    TechnicalResult,
)
from app.domain.validators import (
    validate_analysis_type,
    validate_bounds,
    validate_interval,
    validate_market,
    validate_symbol,
)

# ---- Enum Tests ----


class TestEnums:
    def test_market_values(self):
        assert Market.BINANCE.value == "binance"
        assert Market.YAHOO.value == "yahoo"

    def test_interval_values(self):
        assert Interval.M15.value == "15m"
        assert Interval.H1.value == "1h"
        assert Interval.H4.value == "4h"
        assert Interval.D1.value == "1d"
        assert Interval.W1.value == "1w"

    def test_analysis_type_values(self):
        assert AnalysisType.FORMING.value == "forming"
        assert AnalysisType.FORMED.value == "formed"
        assert AnalysisType.DIVERGENCE.value == "divergence"

    def test_status_values(self):
        assert Status.COMPLETED.value == "completed"
        assert Status.NO_RESULT.value == "no_result"

    def test_error_code_values(self):
        assert ErrorCode.INVALID_PARAMS.value == "INVALID_PARAMS"
        assert ErrorCode.MARKET_DATA_UNAVAILABLE.value == "MARKET_DATA_UNAVAILABLE"


# ---- Schema Tests ----


class TestAnalyzeRequest:
    def test_valid_request(self):
        req = AnalyzeRequest(
            market=Market.BINANCE,
            symbol="BTCUSDT",
            interval=Interval.D1,
        )
        assert req.market == Market.BINANCE
        assert req.symbol == "BTCUSDT"
        assert req.interval == Interval.D1
        assert req.limit_to == 10
        assert req.percent_complete == 0.8
        assert req.candles == 1000

    def test_symbol_uppercase(self):
        req = AnalyzeRequest(
            market=Market.YAHOO,
            symbol="aapl",
            interval=Interval.H1,
        )
        assert req.symbol == "AAPL"

    def test_symbol_stripped(self):
        req = AnalyzeRequest(
            market=Market.BINANCE,
            symbol="  btcusdt  ",
            interval=Interval.D1,
        )
        assert req.symbol == "BTCUSDT"

    def test_default_values(self):
        req = AnalyzeRequest(
            market=Market.BINANCE,
            symbol="ETHUSDT",
            interval=Interval.H4,
        )
        assert req.analysis_type == AnalysisType.FORMING
        assert req.limit_to == 10
        assert req.percent_complete == 0.8

    def test_custom_values(self):
        req = AnalyzeRequest(
            market=Market.YAHOO,
            symbol="MSFT",
            interval=Interval.W1,
            analysis_type=AnalysisType.FORMED,
            limit_to=5,
            percent_complete=0.9,
            candles=2000,
        )
        assert req.limit_to == 5
        assert req.percent_complete == 0.9
        assert req.candles == 2000

    def test_invalid_symbol_too_long(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(
                market=Market.BINANCE,
                symbol="A" * 25,
                interval=Interval.D1,
            )

    def test_invalid_limit_to_negative(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(
                market=Market.BINANCE,
                symbol="BTCUSDT",
                interval=Interval.D1,
                limit_to=-1,
            )

    def test_invalid_limit_to_too_large(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(
                market=Market.BINANCE,
                symbol="BTCUSDT",
                interval=Interval.D1,
                limit_to=200,
            )

    def test_invalid_percent_complete_low(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(
                market=Market.BINANCE,
                symbol="BTCUSDT",
                interval=Interval.D1,
                percent_complete=0.01,
            )

    def test_invalid_percent_complete_high(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(
                market=Market.BINANCE,
                symbol="BTCUSDT",
                interval=Interval.D1,
                percent_complete=1.5,
            )

    def test_invalid_candles_low(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(
                market=Market.BINANCE,
                symbol="BTCUSDT",
                interval=Interval.D1,
                candles=50,
            )

    def test_invalid_candles_high(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(
                market=Market.BINANCE,
                symbol="BTCUSDT",
                interval=Interval.D1,
                candles=10000,
            )

    def test_idempotency_key(self):
        req = AnalyzeRequest(
            market=Market.BINANCE,
            symbol="BTCUSDT",
            interval=Interval.D1,
            idempotency_key="abc123",
        )
        assert req.idempotency_key == "abc123"

    def test_idempotency_key_too_long(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(
                market=Market.BINANCE,
                symbol="BTCUSDT",
                interval=Interval.D1,
                idempotency_key="a" * 100,
            )


class TestChartMeta:
    def test_defaults(self):
        chart = ChartMeta()
        assert chart.format == "png"
        assert chart.path is None
        assert chart.url is None

    def test_custom(self):
        chart = ChartMeta(width=800, height=600, path="charts/abc.png")
        assert chart.width == 800
        assert chart.height == 600
        assert chart.path == "charts/abc.png"


class TestTechnicalResult:
    def test_defaults(self):
        tech = TechnicalResult()
        assert tech.pattern_family is None
        assert tech.divergences == {}

    def test_with_position(self):
        tech = TechnicalResult(
            pattern_family="XABCD",
            entry_price=100.0,
            stop_loss=95.0,
            target_price=110.0,
            risk_reward_ratio=2.0,
        )
        assert tech.pattern_family == "XABCD"
        assert tech.entry_price == 100.0


class TestInterpretation:
    def test_defaults(self):
        interp = Interpretation()
        assert interp.sentiment is None
        assert interp.summary is None

    def test_with_data(self):
        interp = Interpretation(
            sentiment="bullish",
            summary="Strong buy signal detected.",
        )
        assert interp.sentiment == "bullish"


class TestAnalysisData:
    def test_minimal(self):
        data = AnalysisData(
            status=Status.COMPLETED,
            market=Market.BINANCE,
            symbol="BTCUSDT",
            interval=Interval.D1,
            analysis_type=AnalysisType.FORMING,
        )
        assert data.status == Status.COMPLETED


class TestResponseSchemas:
    def test_success_response(self):
        data = AnalysisData(
            status=Status.COMPLETED,
            market=Market.BINANCE,
            symbol="BTCUSDT",
            interval=Interval.D1,
            analysis_type=AnalysisType.FORMING,
        )
        resp = SuccessResponse(data=data)
        assert resp.success is True

    def test_error_response(self):
        from app.domain.schemas import ErrorDetail

        resp = ErrorResponse(
            error=ErrorDetail(
                code=ErrorCode.INVALID_PARAMS,
                message="Bad request",
                retryable=False,
                request_id="abc123",
            )
        )
        assert resp.success is False
        assert resp.error.code == ErrorCode.INVALID_PARAMS

    def test_health_response(self):
        resp = HealthResponse(status="ok")
        assert resp.status == "ok"
        assert resp.version == "0.2.0"

    def test_markets_response(self):
        resp = MarketsResponse(
            markets=["binance", "yahoo"],
            intervals=["1d", "1h"],
            analysis_types=["forming"],
        )
        assert len(resp.markets) == 2


# ---- Validator Tests ----


class TestValidateSymbol:
    def test_valid_symbol(self):
        assert validate_symbol("BTCUSDT") == "BTCUSDT"

    def test_lowercase_symbol(self):
        assert validate_symbol("aapl") == "AAPL"

    def test_symbol_with_whitespace(self):
        assert validate_symbol("  msft  ") == "MSFT"

    def test_empty_symbol(self):
        with pytest.raises(AppError) as exc_info:
            validate_symbol("")
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS

    def test_blacklisted_symbol(self):
        with pytest.raises(AppError) as exc_info:
            validate_symbol("NULL")
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS

    def test_invalid_characters(self):
        with pytest.raises(AppError) as exc_info:
            validate_symbol("BTC-USD")
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS

    def test_too_long_symbol(self):
        with pytest.raises(AppError) as exc_info:
            validate_symbol("A" * 25)
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS


class TestValidateInterval:
    def test_valid_intervals(self):
        assert validate_interval("1d") == Interval.D1
        assert validate_interval("1h") == Interval.H1
        assert validate_interval("15m") == Interval.M15
        assert validate_interval("4h") == Interval.H4
        assert validate_interval("1w") == Interval.W1
        assert validate_interval("1m") == Interval.M1
        assert validate_interval("5m") == Interval.M5

    def test_invalid_interval(self):
        with pytest.raises(AppError) as exc_info:
            validate_interval("3m")
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS
        assert "3m" in exc_info.value.message

    def test_empty_interval(self):
        with pytest.raises(AppError) as exc_info:
            validate_interval("")
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS


class TestValidateMarket:
    def test_valid_markets(self):
        assert validate_market("binance") == Market.BINANCE
        assert validate_market("yahoo") == Market.YAHOO

    def test_invalid_market(self):
        with pytest.raises(AppError) as exc_info:
            validate_market("kraken")
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS


class TestValidateAnalysisType:
    def test_valid_types(self):
        assert validate_analysis_type("forming") == AnalysisType.FORMING
        assert validate_analysis_type("formed") == AnalysisType.FORMED
        assert validate_analysis_type("divergence") == AnalysisType.DIVERGENCE

    def test_invalid_type(self):
        with pytest.raises(AppError) as exc_info:
            validate_analysis_type("invalid")
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS


class TestValidateBounds:
    def test_valid_bounds(self):
        # Should not raise
        validate_bounds(10, 0.8, 1000)

    def test_limit_to_too_low(self):
        with pytest.raises(AppError) as exc_info:
            validate_bounds(0, 0.8, 1000)
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS

    def test_limit_to_too_high(self):
        with pytest.raises(AppError) as exc_info:
            validate_bounds(200, 0.8, 1000)
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS

    def test_percent_complete_too_low(self):
        with pytest.raises(AppError) as exc_info:
            validate_bounds(10, 0.01, 1000)
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS

    def test_percent_complete_too_high(self):
        with pytest.raises(AppError) as exc_info:
            validate_bounds(10, 1.5, 1000)
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS

    def test_candles_too_low(self):
        with pytest.raises(AppError) as exc_info:
            validate_bounds(10, 0.8, 50)
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS

    def test_candles_too_high(self):
        with pytest.raises(AppError) as exc_info:
            validate_bounds(10, 0.8, 10000)
        assert exc_info.value.code == AppErrorCode.INVALID_PARAMS

    def test_boundary_values(self):
        # Exact boundary values should pass
        validate_bounds(1, 0.1, 100)
        validate_bounds(100, 1.0, 5000)
