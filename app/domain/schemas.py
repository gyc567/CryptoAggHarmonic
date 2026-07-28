"""Pydantic schemas for request/response validation."""
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator
from app.domain.enums import Market, Interval, AnalysisType, Status, ErrorCode


class AnalyzeRequest(BaseModel):
    """Structured analysis request."""
    market: Market = Market.FUTURES  # 默认永续合约
    symbol: str = Field(..., min_length=1, max_length=20)
    interval: Interval
    analysis_type: AnalysisType = AnalysisType.FORMING
    limit_to: int = Field(default=10, ge=1, le=100)
    percent_complete: float = Field(default=0.8, ge=0.1, le=1.0)
    candles: int = Field(default=1000, ge=100, le=5000)
    idempotency_key: Optional[str] = Field(default=None, max_length=64)

    @field_validator("symbol")
    @classmethod
    def symbol_uppercase(cls, v: str) -> str:
        return v.upper().strip()


class ChartMeta(BaseModel):
    """Chart metadata (no base64 data)."""
    format: str = "png"
    width: Optional[int] = None
    height: Optional[int] = None
    path: Optional[str] = None
    url: Optional[str] = None


class TimingInfo(BaseModel):
    """Analysis timing information."""
    duration_ms: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class SignalTarget(BaseModel):
    """One take-profit rung of a trade signal."""
    label: str
    price: float
    fib_basis: Optional[str] = None
    close_pct: Optional[int] = None
    move_stop_to: Optional[str] = None


class Signal(BaseModel):
    """Executable trade signal with strict stop loss and TP ladder."""
    status: str
    grade: str
    direction: str
    pattern_name: str
    family: str
    formed: bool
    entry_zone: list[float]
    entry_reference: float
    stop_loss: float
    stop_basis: Optional[str] = None
    stop_level: Optional[str] = None  # conservative | standard | aggressive
    invalidation_point: Optional[float] = None  # structural invalidation point
    targets: list[SignalTarget] = Field(default_factory=list)
    net_rr_tp1: Optional[float] = None
    net_rr_tp2: Optional[float] = None
    confluence_score: Optional[int] = None
    confluence: dict = Field(default_factory=dict)
    htf_trend: Optional[str] = None
    # v4 validity metadata
    reasoning: Optional[str] = None
    sharpe: Optional[float] = None
    regime: Optional[str] = None
    position_multiplier: Optional[float] = None
    stability_score: Optional[int] = None
    trap_score: Optional[int] = None


class TechnicalResult(BaseModel):
    """Deterministic technical analysis output."""
    pattern_family: Optional[str] = None
    pattern_type: Optional[str] = None
    direction: Optional[str] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    confidence: Optional[str] = None
    divergences: dict = Field(default_factory=dict)
    raw_patterns: dict = Field(default_factory=dict)
    signal: Optional[Signal] = None
    # The analysis type the engine actually used ("formed"/"forming"/None).
    # Distinct from pattern_type, which is raw detection info.
    resolved_type: Optional[str] = None


class Interpretation(BaseModel):
    """Model-generated interpretation."""
    sentiment: Optional[str] = None
    summary: Optional[str] = None
    timeframes: dict = Field(default_factory=dict)
    raw_response: Optional[str] = None


class AnalysisData(BaseModel):
    """Complete analysis response data."""
    analysis_id: str = ""
    status: Status
    market: Market
    symbol: str
    interval: Interval
    analysis_type: AnalysisType
    parameters: dict = Field(default_factory=dict)
    technical_result: TechnicalResult = Field(default_factory=TechnicalResult)
    interpretation: Interpretation = Field(default_factory=Interpretation)
    chart: ChartMeta = Field(default_factory=ChartMeta)
    timing: TimingInfo = Field(default_factory=TimingInfo)
    binance_ws_url: Optional[str] = None  # 客户端直连 Binance WS（仅 FUTURES）


class SuccessResponse(BaseModel):
    """Standard success response wrapper."""
    success: bool = True
    data: AnalysisData


class ErrorDetail(BaseModel):
    """Standard error detail."""
    code: ErrorCode
    message: str
    retryable: bool = False
    request_id: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard error response wrapper."""
    success: bool = False
    error: ErrorDetail


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    version: str = "0.2.0"
    timestamp: Optional[str] = None
    checks: Optional[dict] = None


class MarketsResponse(BaseModel):
    """Supported markets and intervals."""
    markets: list[str]
    intervals: list[str]
    analysis_types: list[str]
