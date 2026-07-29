"""Input validators for domain models."""

import re

from app.api.errors import AppError, ErrorCode
from app.domain.enums import AnalysisType, Interval, Market

# Symbol format: uppercase letters and numbers only, no special chars
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,20}$")

# Known invalid / dangerous symbols
_SYMBOL_BLACKLIST = {
    "",
    "NULL",
    "NONE",
    "TEST",
    "EXAMPLE",
    "ADMIN",
    "ROOT",
}


def validate_symbol(symbol: str) -> str:
    """Validate and normalize symbol.

    Args:
        symbol: Raw symbol string.

    Returns:
        Uppercase stripped symbol.

    Raises:
        AppError: If symbol is invalid.
    """
    normalized = symbol.upper().strip()
    if not normalized:
        raise AppError(
            ErrorCode.INVALID_PARAMS,
            "Symbol is required.",
        )
    if normalized in _SYMBOL_BLACKLIST:
        raise AppError(
            ErrorCode.INVALID_PARAMS,
            f"Symbol '{normalized}' is not allowed.",
        )
    if not _SYMBOL_RE.match(normalized):
        raise AppError(
            ErrorCode.INVALID_PARAMS,
            f"Symbol '{normalized}' contains invalid characters. Use only letters and numbers.",
        )
    return normalized


def validate_interval(interval: str) -> Interval:
    """Validate interval against allowed enum values.

    Args:
        interval: Raw interval string.

    Returns:
        Validated Interval enum.

    Raises:
        AppError: If interval is not supported.
    """
    try:
        return Interval(interval)
    except ValueError as exc:
        raise AppError(
            ErrorCode.INVALID_PARAMS,
            f"Interval '{interval}' is not supported. " f"Supported: {[i.value for i in Interval]}",
        ) from exc


def validate_market(market: str) -> Market:
    """Validate market against allowed enum values.

    Args:
        market: Raw market string.

    Returns:
        Validated Market enum.

    Raises:
        AppError: If market is not supported.
    """
    try:
        return Market(market)
    except ValueError as exc:
        raise AppError(
            ErrorCode.INVALID_PARAMS,
            f"Market '{market}' is not supported. " f"Supported: {[m.value for m in Market]}",
        ) from exc


def validate_analysis_type(analysis_type: str) -> AnalysisType:
    """Validate analysis type against allowed enum values.

    Args:
        analysis_type: Raw analysis type string.

    Returns:
        Validated AnalysisType enum.

    Raises:
        AppError: If analysis type is not supported.
    """
    try:
        return AnalysisType(analysis_type)
    except ValueError as exc:
        raise AppError(
            ErrorCode.INVALID_PARAMS,
            f"Analysis type '{analysis_type}' is not supported. " f"Supported: {[a.value for a in AnalysisType]}",
        ) from exc


def validate_bounds(limit_to: int, percent_complete: float, candles: int) -> None:
    """Validate numeric parameter bounds.

    Args:
        limit_to: Pattern limit.
        percent_complete: Formation completion ratio.
        candles: Number of candles to fetch.

    Raises:
        AppError: If any parameter is out of bounds.
    """
    if not (1 <= limit_to <= 100):
        raise AppError(
            ErrorCode.INVALID_PARAMS,
            f"limit_to must be between 1 and 100, got {limit_to}.",
        )
    if not (0.1 <= percent_complete <= 1.0):
        raise AppError(
            ErrorCode.INVALID_PARAMS,
            f"percent_complete must be between 0.1 and 1.0, got {percent_complete}.",
        )
    if not (100 <= candles <= 5000):
        raise AppError(
            ErrorCode.INVALID_PARAMS,
            f"candles must be between 100 and 5000, got {candles}.",
        )
