"""Domain enums for Pyharmonics SaaS API."""

from enum import Enum


class Market(str, Enum):
    """Supported market data sources."""

    BINANCE = "binance"  # 现货
    FUTURES = "futures"  # USDT-M 永续合约
    YAHOO = "yahoo"


class Interval(str, Enum):
    """Supported candle intervals."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"


class AnalysisType(str, Enum):
    """Supported analysis types.

    AUTO runs the full detection pipeline (forming + formed + divergence)
    and lets the signal engine decide what was actually found, reported
    back via ``TechnicalResult.resolved_type``.
    """

    AUTO = "auto"
    FORMING = "forming"
    FORMED = "formed"
    DIVERGENCE = "divergence"


class Status(str, Enum):
    """Analysis status values."""

    CREATED = "created"
    VALIDATING = "validating"
    FETCHING_MARKET_DATA = "fetching_market_data"
    DETECTING_PATTERNS = "detecting_patterns"
    INTERPRETING = "interpreting"
    RENDERING_CHART = "rendering_chart"
    COMPLETED = "completed"
    NO_RESULT = "no_result"
    FAILED_UPSTREAM = "failed_upstream"
    FAILED_MODEL = "failed_model"
    FAILED_CHART = "failed_chart"
    REJECTED = "rejected"


class ErrorCode(str, Enum):
    """Standard error codes for API responses."""

    INVALID_PARAMS = "INVALID_PARAMS"
    MARKET_DATA_UNAVAILABLE = "MARKET_DATA_UNAVAILABLE"
    NO_PATTERNS_FOUND = "NO_PATTERNS_FOUND"
    DETECTION_ERROR = "DETECTION_ERROR"
    MODEL_ERROR = "MODEL_ERROR"
    CHART_ERROR = "CHART_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    DUPLICATE_SYMBOL = "DUPLICATE_SYMBOL"
    WATCHLIST_LIMIT_REACHED = "WATCHLIST_LIMIT_REACHED"
    WATCHLIST_UNKNOWN_SYMBOL = "WATCHLIST_UNKNOWN_SYMBOL"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
