"""Layer-3 schema contract tests for app.domain.schemas.

Two guarantees are pinned here:

1. **Field-level constraints** — every Annotated[..., Field(...)] declared in
   :mod:`app.domain.schemas` actually rejects the bad inputs the annotation
   promises. If a future refactor weakens a constraint (drops ``gt=0``,
   widens ``max_length``, ...) the test that exercises that boundary fails.
2. **Cross-field invariants** — the ``@model_validator`` on
   :class:`AnalyzeRequest` (candles >= 2*limit_to) fires for the documented
   violation and does not falsely trigger on the happy path.

These tests are deliberately strict: any change to the schema that
*appears* to loosen a constraint without a matching test update is a
regression that should be caught in code review or by CI.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.enums import AnalysisType, Interval, Market
from app.domain.schemas import (
    AnalyzeRequest,
    AnalysisData,
    ChartMeta,
    ErrorResponse,
    HealthResponse,
    Interpretation,
    MarketsResponse,
    Signal,
    SignalTarget,
    SuccessResponse,
    TechnicalResult,
    TimingInfo,
)
from app.domain.enums import Status, ErrorCode


# ---------------------------------------------------------------------------
# AnalyzeRequest — request body
# ---------------------------------------------------------------------------


class TestAnalyzeRequestFields:
    """Field-level invariants on the public AnalyzeRequest model."""

    def test_happy_path(self):
        req = AnalyzeRequest(
            symbol="BTCUSDT",
            interval=Interval.H1,
            analysis_type=AnalysisType.AUTO,
        )
        assert req.symbol == "BTCUSDT"
        assert req.interval is Interval.H1
        assert req.market is Market.FUTURES  # default

    def test_symbol_is_uppercased_and_trimmed(self):
        req = AnalyzeRequest(symbol="  btc usdt ", interval=Interval.H1)
        assert req.symbol == "BTC USDT"  # strips spaces but inner spaces stay

    def test_rejects_empty_symbol(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(symbol="", interval=Interval.H1)

    def test_rejects_symbol_too_long(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(symbol="X" * 21, interval=Interval.H1)

    def test_rejects_limit_to_zero(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(symbol="BTCUSDT", interval=Interval.H1, limit_to=0)

    def test_rejects_limit_to_above_100(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(symbol="BTCUSDT", interval=Interval.H1, limit_to=200)

    def test_rejects_candles_below_100(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(symbol="BTCUSDT", interval=Interval.H1, candles=50)

    def test_rejects_candles_above_5000(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(symbol="BTCUSDT", interval=Interval.H1, candles=5001)

    def test_rejects_percent_complete_zero(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(symbol="BTCUSDT", interval=Interval.H1, percent_complete=0)

    def test_rejects_percent_complete_one(self):
        # ge=0.1, le=1.0 → exactly 1.0 is allowed; 1.01 is not.
        with pytest.raises(ValidationError):
            AnalyzeRequest(symbol="BTCUSDT", interval=Interval.H1, percent_complete=1.01)

    def test_idempotency_key_max_length(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(
                symbol="BTCUSDT",
                interval=Interval.H1,
                idempotency_key="x" * 65,
            )


class TestAnalyzeRequestCrossField:
    """The @model_validator that couples limit_to and candles."""

    def test_candles_must_be_at_least_two_times_limit_to(self):
        # 10 candidates requested but only 10 bars — the engine cannot
        # produce a meaningful ranking. The validator surfaces this at the
        # I/O boundary rather than letting the engine return empty.
        with pytest.raises(ValidationError, match="candles"):
            AnalyzeRequest(
                symbol="BTCUSDT",
                interval=Interval.H1,
                limit_to=10,
                candles=10,
            )

    def test_one_more_candle_passes(self):
        # 2*limit_to passes; candles must also satisfy its own ge=100.
        # With limit_to=50 the boundary is exactly candles=100.
        req = AnalyzeRequest(
            symbol="BTCUSDT",
            interval=Interval.H1,
            limit_to=50,
            candles=100,
        )
        assert req.candles == 100

    def test_one_fewer_candle_fails(self):
        # 2*limit_to - 1 still fails the cross-field rule.
        with pytest.raises(ValidationError):
            AnalyzeRequest(
                symbol="BTCUSDT",
                interval=Interval.H1,
                limit_to=50,
                candles=99,
            )


# ---------------------------------------------------------------------------
# Signal — response payload sub-schema
# ---------------------------------------------------------------------------


class TestSignalFields:
    """Field-level constraints on the trade-signal sub-schema."""

    def _minimal(self, **overrides) -> dict:
        base = dict(
            status="confirmed",
            grade="A",
            direction="long",
            pattern_name="gartley",
            family="XABCD",
            formed=True,
            entry_zone=[99.0, 101.0],
            entry_reference=100.0,
            stop_loss=95.0,
            targets=[],
            net_rr_tp1=2.0,
            net_rr_tp2=3.0,
            confluence_score=80,
        )
        base.update(overrides)
        return base

    def test_happy_path(self):
        sig = Signal(**self._minimal())
        assert sig.grade == "A"
        assert sig.entry_zone == [99.0, 101.0]

    def test_rejects_zero_entry_reference(self):
        with pytest.raises(ValidationError):
            Signal(**self._minimal(entry_reference=0.0))

    def test_rejects_negative_stop_loss(self):
        with pytest.raises(ValidationError):
            Signal(**self._minimal(stop_loss=-1.0))

    def test_rejects_confluence_score_above_100(self):
        with pytest.raises(ValidationError):
            Signal(**self._minimal(confluence_score=101))

    def test_rejects_negative_net_rr_tp1(self):
        with pytest.raises(ValidationError):
            Signal(**self._minimal(net_rr_tp1=-0.5))


class TestSignalTargetFields:
    def test_happy_path(self):
        t = SignalTarget(label="TP1", price=110.0)
        assert t.label == "TP1"

    def test_rejects_zero_price(self):
        with pytest.raises(ValidationError):
            SignalTarget(label="TP1", price=0.0)

    def test_rejects_negative_close_pct(self):
        with pytest.raises(ValidationError):
            SignalTarget(label="TP1", price=110.0, close_pct=-1)

    def test_rejects_close_pct_above_100(self):
        with pytest.raises(ValidationError):
            SignalTarget(label="TP1", price=110.0, close_pct=101)


# ---------------------------------------------------------------------------
# Response envelopes — happy-path shape checks
# ---------------------------------------------------------------------------


class TestResponseEnvelopes:
    def test_health_response_defaults(self):
        h = HealthResponse()
        assert h.status == "ok"
        assert h.version == "0.2.0"
        assert h.timestamp is None

    def test_markets_response_happy_path(self):
        m = MarketsResponse(
            markets=["binance", "yahoo"],
            intervals=["1h", "4h"],
            analysis_types=["forming", "formed"],
        )
        assert "binance" in m.markets

    def test_markets_response_rejects_empty_lists(self):
        # min_length=1 on all three lists — empty arrays are nonsensical
        # for a "what's supported" response.
        with pytest.raises(ValidationError):
            MarketsResponse(markets=[], intervals=["1h"], analysis_types=["forming"])

    def test_error_response_happy_path(self):
        e = ErrorResponse(
            error={"code": ErrorCode.INVALID_PARAMS, "message": "bad"}
        )
        assert e.success is False
        assert e.error.code is ErrorCode.INVALID_PARAMS

    def test_success_response_wraps_data(self):
        data = AnalysisData(
            status=Status.COMPLETED,
            market=Market.FUTURES,
            symbol="BTCUSDT",
            interval=Interval.H1,
            analysis_type=AnalysisType.FORMING,
        )
        s = SuccessResponse(data=data)
        assert s.success is True
        assert s.data.symbol == "BTCUSDT"

    def test_chart_meta_rejects_zero_dimensions(self):
        with pytest.raises(ValidationError):
            ChartMeta(format="png", width=0)

    def test_chart_meta_rejects_huge_dimensions(self):
        with pytest.raises(ValidationError):
            ChartMeta(format="png", width=10000)

    def test_timing_info_rejects_negative_duration(self):
        with pytest.raises(ValidationError):
            TimingInfo(duration_ms=-1)

    def test_interpretation_rejects_huge_summary(self):
        with pytest.raises(ValidationError):
            Interpretation(summary="x" * 4097)


# ---------------------------------------------------------------------------
# Cross-model invariant: nested schema validation flows
# ---------------------------------------------------------------------------


class TestNestedValidation:
    """Building AnalysisData with invalid nested fields must bubble up."""

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            AnalysisData(
                status="not-a-real-status",  # type: ignore[arg-type]
                market=Market.FUTURES,
                symbol="BTCUSDT",
                interval=Interval.H1,
                analysis_type=AnalysisType.FORMING,
            )

    def test_invalid_market_rejected(self):
        with pytest.raises(ValidationError):
            AnalysisData(
                status=Status.COMPLETED,
                market="bitstamp",  # type: ignore[arg-type]
                symbol="BTCUSDT",
                interval=Interval.H1,
                analysis_type=AnalysisType.FORMING,
            )