"""Layer-3 schema contract tests for app.domain.{rsi_trend_schemas,vibe_schemas}.

Same guarantee pattern as ``test_schemas_contract.py`` for
:mod:`app.domain.schemas`:

1. Field-level constraints declared with ``Field(...)`` actually reject
   the bad inputs the annotation promises.
2. Cross-field validators (``@model_validator``) fire for the documented
   violation and do not falsely trigger on the happy path.
3. Discriminated unions (``VibeEvent``) route by ``type`` and reject
   events that mix fields from two variants.

These tests pin the surface that ``app/api/vibe_routes.py`` and
``app/api/rsi_trend_routes.py`` rely on. Any future refactor that loosens
a constraint, widens a Literal, or breaks discriminator routing should
trip one of these tests in CI.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.rsi_trend_schemas import (
    RsiTrendBacktestRequest,
    RsiTrendScanRequest,
)
from app.domain.vibe_schemas import (
    CardEvent,
    CreateSessionRequest,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    PollEventsResponse,
    RunStartedEvent,
    SendMessageRequest,
    ToolCallEndEvent,
    ToolCallStartEvent,
    VibeEvent,
)

# ---------------------------------------------------------------------------
# RsiTrendScanRequest / RsiTrendBacktestRequest — request bodies
# ---------------------------------------------------------------------------


class TestRsiTrendScanRequestFields:
    """Field-level invariants on the shared scan request model."""

    def test_happy_path_defaults(self):
        req = RsiTrendScanRequest(symbol="BTCUSDT")
        assert req.market == "binance"
        assert req.interval == "4h"
        assert req.rsi_zone == "extreme"
        assert req.atr_mult == 1.0
        assert req.reward_risk == 2.0
        assert req.min_quality_score == 0.0

    def test_rejects_empty_symbol(self):
        with pytest.raises(ValidationError):
            RsiTrendScanRequest(symbol="")

    def test_rejects_symbol_too_long(self):
        with pytest.raises(ValidationError):
            RsiTrendScanRequest(symbol="X" * 31)

    def test_rejects_atr_mult_below_half(self):
        # ge=0.5 — anything smaller is too tight to be a real ATR multiple.
        with pytest.raises(ValidationError):
            RsiTrendScanRequest(symbol="BTCUSDT", atr_mult=0.49)

    def test_rejects_atr_mult_above_three(self):
        # le=3.0 — beyond this, the stop is so wide it never gets hit.
        with pytest.raises(ValidationError):
            RsiTrendScanRequest(symbol="BTCUSDT", atr_mult=3.01)

    def test_rejects_reward_risk_below_one(self):
        # ge=1.0 — a sub-1R target is never a real trade.
        with pytest.raises(ValidationError):
            RsiTrendScanRequest(symbol="BTCUSDT", reward_risk=0.99)

    def test_rejects_reward_risk_above_five(self):
        with pytest.raises(ValidationError):
            RsiTrendScanRequest(symbol="BTCUSDT", reward_risk=5.01)

    def test_rejects_min_quality_score_negative(self):
        with pytest.raises(ValidationError):
            RsiTrendScanRequest(symbol="BTCUSDT", min_quality_score=-0.01)

    def test_rejects_min_quality_score_above_100(self):
        with pytest.raises(ValidationError):
            RsiTrendScanRequest(symbol="BTCUSDT", min_quality_score=100.01)

    def test_rejects_unknown_market(self):
        with pytest.raises(ValidationError):
            RsiTrendScanRequest(symbol="BTCUSDT", market="coinbase")  # type: ignore[arg-type]

    def test_rejects_unknown_interval(self):
        with pytest.raises(ValidationError):
            RsiTrendScanRequest(symbol="BTCUSDT", interval="2h")  # type: ignore[arg-type]

    def test_rejects_unknown_rsi_zone(self):
        with pytest.raises(ValidationError):
            RsiTrendScanRequest(symbol="BTCUSDT", rsi_zone="neutral")  # type: ignore[arg-type]


class TestRsiTrendScanRequestCrossField:
    """The market×interval cross-field rule (yahoo → 1d/1w only)."""

    def test_yahoo_with_4h_rejected(self):
        with pytest.raises(ValidationError, match="yahoo"):
            RsiTrendScanRequest(market="yahoo", symbol="AAPL", interval="4h")

    def test_yahoo_with_1d_passes(self):
        req = RsiTrendScanRequest(market="yahoo", symbol="AAPL", interval="1d")
        assert req.interval == "1d"

    def test_binance_with_4h_passes(self):
        req = RsiTrendScanRequest(market="binance", symbol="BTCUSDT", interval="4h")
        assert req.interval == "4h"

    def test_binance_with_1d_passes(self):
        req = RsiTrendScanRequest(market="binance", symbol="BTCUSDT", interval="1d")
        assert req.interval == "1d"


class TestRsiTrendBacktestRequest:
    """The backtest endpoint inherits the scan constraints and adds lookback bounds."""

    def test_inherits_scan_validators(self):
        with pytest.raises(ValidationError):
            RsiTrendBacktestRequest(market="yahoo", symbol="AAPL", interval="4h")

    def test_lookback_default(self):
        req = RsiTrendBacktestRequest(symbol="BTCUSDT")
        assert req.lookback_days == 180
        assert req.partial_mode is False
        assert req.trailing_stop is False

    def test_rejects_lookback_below_60(self):
        with pytest.raises(ValidationError):
            RsiTrendBacktestRequest(symbol="BTCUSDT", lookback_days=59)

    def test_rejects_lookback_above_365(self):
        with pytest.raises(ValidationError):
            RsiTrendBacktestRequest(symbol="BTCUSDT", lookback_days=366)

    def test_accepts_lookback_at_lower_bound(self):
        req = RsiTrendBacktestRequest(symbol="BTCUSDT", lookback_days=60)
        assert req.lookback_days == 60

    def test_accepts_lookback_at_upper_bound(self):
        req = RsiTrendBacktestRequest(symbol="BTCUSDT", lookback_days=365)
        assert req.lookback_days == 365


# ---------------------------------------------------------------------------
# Vibe — request/response models
# ---------------------------------------------------------------------------


class TestCreateSessionRequest:
    def test_happy_path_empty(self):
        req = CreateSessionRequest()
        assert req.title is None
        assert req.context == {}

    def test_rejects_title_above_max_length(self):
        with pytest.raises(ValidationError):
            CreateSessionRequest(title="x" * 201)

    def test_accepts_title_at_max_length(self):
        req = CreateSessionRequest(title="x" * 200)
        assert req.title is not None and len(req.title) == 200


class TestSendMessageRequest:
    def test_happy_path(self):
        req = SendMessageRequest(content="hello")
        assert req.content == "hello"
        assert req.attachments == []

    def test_rejects_empty_content(self):
        with pytest.raises(ValidationError):
            SendMessageRequest(content="")

    def test_rejects_content_above_max_length(self):
        with pytest.raises(ValidationError):
            SendMessageRequest(content="x" * 4001)


# ---------------------------------------------------------------------------
# Vibe event stream — discriminated union
# ---------------------------------------------------------------------------


def _base_event(**overrides) -> dict:
    """The minimum payload every typed event needs."""
    base = dict(
        event_id="evt_1",
        run_id="run_1",
        ts="2026-07-29T00:00:00Z",
    )
    base.update(overrides)
    return base


class TestVibeEventDiscriminator:
    """The Annotated[Union, Field(discriminator='type')] routing must work for every variant."""

    def test_run_started_routes_correctly(self):
        e = VibeEvent.model_validate(_base_event(type="run_started"))
        assert isinstance(e, RunStartedEvent)
        assert e.status == "running"

    def test_tool_call_start_routes_correctly(self):
        e = VibeEvent.model_validate(
            _base_event(
                type="tool_call_start",
                call_id="c1",
                tool="get_price",
                input={"symbol": "BTCUSDT"},
            )
        )
        assert isinstance(e, ToolCallStartEvent)
        assert e.tool == "get_price"
        assert e.input == {"symbol": "BTCUSDT"}

    def test_tool_call_end_routes_correctly(self):
        e = VibeEvent.model_validate(
            _base_event(
                type="tool_call_end",
                call_id="c1",
                tool="get_price",
                output={"price": 100.0},
            )
        )
        assert isinstance(e, ToolCallEndEvent)

    def test_delta_routes_correctly(self):
        e = VibeEvent.model_validate(_base_event(type="delta", content="hello"))
        assert isinstance(e, DeltaEvent)
        assert e.content == "hello"

    def test_card_routes_correctly(self):
        e = VibeEvent.model_validate(
            _base_event(
                type="card",
                card_type="trade_signal",
                payload={"direction": "long"},
            )
        )
        assert isinstance(e, CardEvent)

    def test_done_routes_correctly(self):
        e = VibeEvent.model_validate(_base_event(type="done"))
        assert isinstance(e, DoneEvent)
        assert e.status == "completed"

    def test_error_routes_correctly(self):
        e = VibeEvent.model_validate(_base_event(type="error", code="NETWORK", message="timeout", retryable=True))
        assert isinstance(e, ErrorEvent)
        assert e.retryable is True

    def test_unknown_event_type_rejected(self):
        with pytest.raises(ValidationError):
            VibeEvent.model_validate(_base_event(type="never_emitted"))

    def test_required_fields_enforced(self):
        # tool_call_start without call_id → ValidationError.
        with pytest.raises(ValidationError):
            VibeEvent.model_validate(_base_event(type="tool_call_start", tool="x", input={}))


class TestVibeEventBaseExtra:
    """extra='forbid' on _VibeEventBase stops typos from leaking into the timeline."""

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            VibeEvent.model_validate(_base_event(type="delta", content="x", typo_field="oops"))


# ---------------------------------------------------------------------------
# PollEventsResponse — envelope shape
# ---------------------------------------------------------------------------


class TestPollEventsResponse:
    def test_happy_path(self):
        r = PollEventsResponse(
            run_id="run_1",
            status="running",
            events=[{"type": "run_started"}],
            has_more=False,
        )
        assert r.has_more is False
        assert len(r.events) == 1
