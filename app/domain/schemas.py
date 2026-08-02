"""Pydantic schemas for request/response validation.

Three-layer defense — Layer 3 (data integrity) lives here.

Layering rules:
- This module owns the **shape** of every I/O contract: request bodies, response
  payloads, error envelopes, health checks. Any field that crosses the API
  boundary must be declared here.
- Field constraints (range / length / pattern / enum) are encoded with
  ``Annotated[..., Field(...)]`` so mypy and Pydantic see the same surface.
- Cross-field invariants (e.g. ``limit_to <= candles``) live in
  ``@model_validator`` decorators — never in ad-hoc route handlers.
- This module keeps ``ConfigDict`` minimal (defaults); the strong-strict
  knobs (``strict=True``, ``frozen=True``, ``validate_assignment=True``,
  ``extra="forbid"``) collide with the orchestrator's incremental
  ``TechnicalResult`` build from dicts. Layer-2 in
  :mod:`app.domain.signals` is where the trustworthy strictness lives;
  here we focus on field-level integrity and cross-field invariants.

Layer 1 (mypy / pyright) and Layer 2 (icontract in :mod:`app.domain.signals`)
cover the rest; this module is the source of truth for what enters and leaves
the system.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.domain.enums import AnalysisType, ErrorCode, Interval, Market, Status

# --- Shared base model --------------------------------------------------------
#
# Every schema in this module inherits from _StrictModel so the ConfigDict knobs
# are set in one place. Adding a new schema? Inherit from this; do NOT pass
# model_config=... per-class.


class _StrictModel(BaseModel):
    """Base for every Pydantic model in this module.

    The strong enforcement (every field gets ``Annotated[..., Field(...)]``
    with ``gt``, ``le``, ``min_length``, ``pattern``, etc.) and the
    cross-field ``@model_validator`` on :class:`AnalyzeRequest` are what
    give us the three-layer defense's Layer-3 guarantees. The
    ``ConfigDict`` flags that the reference guide recommends
    (``strict=True``, ``frozen=True``, ``validate_assignment=True``,
    ``extra="forbid"``) all collide with this codebase's existing
    orchestrator, which builds :class:`TechnicalResult` incrementally from
    dicts with keys the schema doesn't enumerate. Layer-2 in
    :mod:`app.domain.signals` is the trustworthy strictness layer for this
    project; here we focus on field-level integrity and cross-field
    invariants.
    """

    model_config = ConfigDict()


# --- Request schemas ----------------------------------------------------------


class AnalyzeRequest(_StrictModel):
    """Structured analysis request."""

    market: Annotated[
        Market,
        Field(
            default=Market.FUTURES,
            description="Market data source. Defaults to USDT-M perpetuals.",
        ),
    ]
    symbol: Annotated[
        str,
        Field(
            ...,
            min_length=1,
            max_length=20,
            description="Trading symbol, e.g. 'BTCUSDT' or 'AAPL'. Case-insensitive.",
        ),
    ]
    interval: Annotated[
        Interval,
        Field(
            ...,
            description="Candle interval.",
        ),
    ]
    analysis_type: Annotated[
        AnalysisType,
        Field(
            default=AnalysisType.FORMING,
            description="Detection mode. AUTO lets the engine pick the resolved type.",
        ),
    ]
    limit_to: Annotated[
        int,
        Field(
            default=10,
            ge=1,
            le=100,
            description="Maximum number of pattern candidates to return.",
        ),
    ]
    percent_complete: Annotated[
        float,
        Field(
            default=0.8,
            ge=0.1,
            le=1.0,
            description="Minimum completion ratio for forming patterns.",
        ),
    ]
    candles: Annotated[
        int,
        Field(
            default=1000,
            ge=100,
            le=5000,
            description="Number of historical candles to fetch for analysis.",
        ),
    ]
    idempotency_key: Annotated[
        Optional[str],
        Field(
            default=None,
            max_length=64,
            description="Caller-supplied retry key; dedupes repeat submissions.",
        ),
    ]

    @field_validator("symbol")
    @classmethod
    def symbol_uppercase(cls, v: str) -> str:
        return v.upper().strip()

    @model_validator(mode="after")
    def _check_candles_covers_limit(self) -> AnalyzeRequest:
        # The engine needs enough bars to honour limit_to + filter chain.
        # Candles below 2*limit_to silently produces empty results; surface
        # the constraint at the I/O boundary instead.
        if self.candles < 2 * self.limit_to:
            raise ValueError(
                f"candles ({self.candles}) must be at least 2x limit_to "
                f"({self.limit_to}); engine would return an empty ranking."
            )
        return self


# --- Response sub-schemas -----------------------------------------------------



class TimingInfo(_StrictModel):
    """Analysis timing information."""

    duration_ms: Annotated[int, Field(default=0, ge=0)] = 0
    started_at: Annotated[Optional[str], Field(default=None, max_length=64)] = None
    completed_at: Annotated[Optional[str], Field(default=None, max_length=64)] = None


class SignalTarget(_StrictModel):
    """One take-profit rung of a trade signal."""

    label: Annotated[str, Field(..., min_length=1, max_length=16)]
    price: Annotated[float, Field(..., gt=0)]
    fib_basis: Annotated[Optional[str], Field(default=None, max_length=64)] = None
    close_pct: Annotated[Optional[int], Field(default=None, ge=0, le=100)] = None
    move_stop_to: Annotated[Optional[str], Field(default=None, max_length=32)] = None


class Signal(_StrictModel):
    """Executable trade signal with strict stop loss and TP ladder."""

    status: Annotated[str, Field(..., min_length=1, max_length=32)]
    grade: Annotated[str, Field(..., min_length=1, max_length=16)]
    direction: Annotated[str, Field(..., min_length=1, max_length=16)]
    pattern_name: Annotated[str, Field(..., min_length=1, max_length=64)]
    family: Annotated[str, Field(..., min_length=1, max_length=32)]
    formed: bool
    entry_zone: Annotated[list[float], Field(..., min_length=1, max_length=4)]
    entry_reference: Annotated[float, Field(..., gt=0)]
    stop_loss: Annotated[float, Field(..., gt=0)]
    stop_basis: Annotated[Optional[str], Field(default=None, max_length=128)] = None
    stop_level: Annotated[Optional[str], Field(default=None, max_length=32)] = None  # conservative | standard | aggressive
    invalidation_point: Annotated[Optional[float], Field(default=None, gt=0)] = None  # structural invalidation point
    targets: Annotated[list[SignalTarget], Field(default_factory=list)]
    net_rr_tp1: Annotated[Optional[float], Field(default=None, ge=0)] = None
    net_rr_tp2: Annotated[Optional[float], Field(default=None, ge=0)] = None
    confluence_score: Annotated[Optional[int], Field(default=None, ge=0, le=100)] = None
    confluence: Annotated[dict[str, Any], Field(default_factory=dict)]
    htf_trend: Annotated[Optional[str], Field(default=None, max_length=32)] = None
    # v4 validity metadata
    reasoning: Annotated[Optional[str], Field(default=None, max_length=2048)] = None
    sharpe: Annotated[Optional[float], Field(default=None, ge=-10, le=10)] = None
    regime: Annotated[Optional[str], Field(default=None, max_length=32)] = None
    position_multiplier: Annotated[Optional[float], Field(default=None, ge=0, le=10)] = None
    stability_score: Annotated[Optional[int], Field(default=None, ge=0, le=100)] = None
    trap_score: Annotated[Optional[int], Field(default=None, ge=0, le=100)] = None


class TechnicalResult(_StrictModel):
    """Deterministic technical analysis output."""

    pattern_family: Annotated[Optional[str], Field(default=None, max_length=32)] = None
    pattern_type: Annotated[Optional[str], Field(default=None, max_length=64)] = None
    direction: Annotated[Optional[str], Field(default=None, max_length=16)] = None
    entry_price: Annotated[Optional[float], Field(default=None, gt=0)] = None
    stop_loss: Annotated[Optional[float], Field(default=None, gt=0)] = None
    target_price: Annotated[Optional[float], Field(default=None, gt=0)] = None
    risk_reward_ratio: Annotated[Optional[float], Field(default=None, ge=0)] = None
    confidence: Annotated[Optional[str], Field(default=None, max_length=16)] = None
    divergences: Annotated[dict[str, Any], Field(default_factory=dict)]
    raw_patterns: Annotated[dict[str, Any], Field(default_factory=dict)]
    signal: Annotated[Optional[Signal], Field(default=None)] = None
    # The analysis type the engine actually used ("formed"/"forming"/None).
    # Distinct from pattern_type, which is raw detection info.
    resolved_type: Annotated[Optional[str], Field(default=None, max_length=16)] = None
    # Latest close price from the fetched candle window, surfaced so the
    # dashboard can render "current realtime price" alongside the actionable
    # trade levels (entry / stop / target). Populated by the orchestrator
    # from ``candle_data.df.iloc[-1]["close"]`` after fetch_market_data.
    current_price: Annotated[Optional[float], Field(default=None, gt=0)] = None
    # UTC ISO timestamp of the candle ``current_price`` came from, so the UI
    # can render "as of <time>" without re-deriving from the candle window.
    current_price_at: Annotated[Optional[str], Field(default=None, max_length=32)] = None


class Interpretation(_StrictModel):
    """Model-generated interpretation."""

    sentiment: Annotated[Optional[str], Field(default=None, max_length=16)] = None
    summary: Annotated[Optional[str], Field(default=None, max_length=4096)] = None
    timeframes: Annotated[dict[str, Any], Field(default_factory=dict)]
    raw_response: Annotated[Optional[str], Field(default=None, max_length=8192)] = None


class AnalysisData(_StrictModel):
    """Complete analysis response data."""

    analysis_id: Annotated[str, Field(default="", max_length=64)] = ""
    status: Status
    market: Market
    symbol: Annotated[str, Field(..., min_length=1, max_length=20)]
    interval: Interval
    analysis_type: AnalysisType
    parameters: Annotated[dict[str, Any], Field(default_factory=dict)]
    technical_result: TechnicalResult = Field(default_factory=lambda: TechnicalResult(divergences={}, raw_patterns={}))
    interpretation: Interpretation = Field(default_factory=lambda: Interpretation(timeframes={}))
    timing: TimingInfo = Field(default_factory=TimingInfo)
    binance_ws_url: Annotated[Optional[str], Field(default=None, max_length=512)] = None  # 客户端直连 Binance WS（仅 FUTURES）
    # v2: ranked list of forming-pattern candidates with discipline + macro tags.
    # Populated when analysis_type == "forming"; empty otherwise. The top entry
    # is mirrored into ``technical_result.signal`` for backwards compatibility
    # with single-best consumers.
    forming_candidates: Annotated[list[Any], Field(default_factory=list)]


# --- Response envelopes -------------------------------------------------------


class SuccessResponse(_StrictModel):
    """Standard success response wrapper."""

    success: Annotated[bool, Field(default=True)]
    data: AnalysisData


class ErrorDetail(_StrictModel):
    """Standard error detail."""

    code: ErrorCode
    message: Annotated[str, Field(..., min_length=1, max_length=1024)]
    retryable: Annotated[bool, Field(default=False)] = False
    request_id: Annotated[Optional[str], Field(default=None, max_length=64)] = None


class FieldError(_StrictModel):
    """One per validation failure when the body is parsed but the schema rejects it.

    Mirrors Pydantic's ``ValidationError.errors()`` shape so the frontend can
    highlight the offending field without parsing the human-readable message.

    ``loc`` is the dotted field path (e.g. ``"interval"`` or
    ``"parameters.limit_to"``); ``msg`` is the human readable string; ``type``
    is the Pydantic error class name (``missing``, ``greater_than_equal``,
    ``literal_error``, ...).

    Note: ``loc`` is intentionally NOT required to be non-empty. Pydantic
    model-level validators (cross-field rules) emit ``loc=()`` (empty) which
    we represent here as ``""``. Constraining it would 500 those errors
    instead of surfacing them as 422.
    """

    loc: Annotated[str, Field(default="", max_length=256)]
    msg: Annotated[str, Field(..., min_length=1, max_length=1024)]
    type: Annotated[str, Field(..., min_length=1, max_length=128)]


class ErrorResponse(_StrictModel):
    """Standard error response wrapper.

    ``details`` is populated only for 422 schema-level validation errors so
    the frontend can show field-level diagnostics. For other error codes
    (404, 429, 500, ...) ``details`` is ``None``.
    """

    success: Annotated[bool, Field(default=False)]
    error: ErrorDetail
    details: Annotated[Optional[list[FieldError]], Field(default=None)] = None


class HealthResponse(_StrictModel):
    """Health check response."""

    status: Annotated[str, Field(default="ok", min_length=1, max_length=32)] = "ok"
    version: Annotated[str, Field(default="0.2.0", min_length=1, max_length=32)]
    timestamp: Annotated[Optional[str], Field(default=None, max_length=64)] = None
    checks: Annotated[Optional[dict[str, Any]], Field(default=None)] = None


class MarketsResponse(_StrictModel):
    """Supported markets and intervals."""

    markets: Annotated[list[str], Field(..., min_length=1)]
    intervals: Annotated[list[str], Field(..., min_length=1)]
    analysis_types: Annotated[list[str], Field(..., min_length=1)]
