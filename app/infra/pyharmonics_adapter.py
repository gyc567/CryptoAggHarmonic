"""Pyharmonics adapter: wraps all pyharmonics calls and converts exceptions."""

import logging
from typing import Any, Optional

# Import pyharmonics classes at module level for testability
from pyharmonics.marketdata import YahooCandleData
from pyharmonics.positions import Position
from pyharmonics.search import DivergenceSearch, HarmonicSearch
from pyharmonics.technicals import OHLCTechnicals

from app.api.errors import AppError, ErrorCode
from app.domain.enums import Interval, Market
from app.domain.schemas import TechnicalResult
from app.infra import tradingview_adapter as tv
from app.infra.marketdata import DirectBinanceCandleData

logger = logging.getLogger(__name__)


def _fetch_from_legacy(market: Market, symbol: str, interval: Interval, candles: int) -> Any:
    """Fallback fetcher using Binance or Yahoo."""
    if market == Market.BINANCE:
        cd = DirectBinanceCandleData()
        cd.get_candles(symbol, interval.value, candles)
        return cd
    elif market == Market.YAHOO:
        cd = YahooCandleData()
        cd.get_candles(symbol, interval.value, candles)
        return cd
    raise AppError(
        ErrorCode.INVALID_PARAMS,
        f"Market '{market.value}' is not supported for data fetching.",
    )


def fetch_market_data(
    market: Market,
    symbol: str,
    interval: Interval,
    candles: int = 1000,
) -> Any:
    """Fetch candle data from market source.

    TradingView is tried first when enabled and the bridge is healthy; on
    failure we fall back to the legacy Binance/Yahoo adapters so the app
    keeps working even if the bridge is down.

    Args:
        market: Market source enum.
        symbol: Uppercase symbol.
        interval: Candle interval.
        candles: Number of candles to fetch.

    Returns:
        Candle data object.

    Raises:
        AppError: If market data is unavailable.
    """
    if tv.is_tradingview_enabled() and tv.is_bridge_healthy():
        try:
            cd = tv.fetch_market_data(
                market=market.value,
                symbol=symbol,
                interval=interval.value,
                candles=candles,
            )
            logger.info(
                "Fetched %s %s from TradingView (%d candles)",
                market.value,
                symbol,
                len(cd.df),
            )
            return cd
        except Exception as e:
            logger.warning(
                "TradingView fetch failed for %s/%s, falling back: %s",
                market.value,
                symbol,
                e,
            )

    try:
        return _fetch_from_legacy(market, symbol, interval, candles)
    except AppError:
        raise
    except Exception as e:
        logger.exception("Failed to fetch market data for %s/%s", market.value, symbol)
        raise AppError(
            ErrorCode.MARKET_DATA_UNAVAILABLE,
            f"暂时无法获取 {symbol} 的行情数据，请稍后重试。",
            retryable=True,
            original_error=e,
        ) from e


def detect_patterns(
    candle_data: Any,
    limit_to: int = 10,
    percent_complete: float = 0.8,
    analysis_type: str = "forming",
) -> dict:
    """Run harmonic and divergence pattern detection.

    Args:
        candle_data: Candle data object with .df, .symbol, .interval.
        limit_to: Max number of patterns to return.
        percent_complete: Minimum completion ratio (0-1).
        analysis_type: Type of analysis - "forming", "formed", or "divergence".

    Returns:
        Dict with position, patterns, divergences, and HTF trend.
    """
    try:
        ohlc = OHLCTechnicals(candle_data.df)
        search = HarmonicSearch(
            symbol=candle_data.symbol,
            interval=candle_data.interval,
            data=ohlc,
            n_jobs=1,
        )
        search.search()
        candidates = search.get_results(
            limit_to=limit_to,
            percent_complete=percent_complete,
        )

        result: dict[str, Any] = {"patterns": {}, "divergences": {}}

        if candidates and len(candidates) > 0:
            best = candidates[0]
            pos: Position = best.position
            result["position"] = pos
            result["patterns"] = {
                "symbol": pos.symbol,
                "family": type(pos).__name__,
                "direction": getattr(pos, "direction", "bullish"),
                "entry": getattr(pos, "strike", None),
                "stop": getattr(pos, "stop", None),
                "targets": getattr(pos, "targets", []),
                "reversal": getattr(pos, "reversal", None),
                "forming": getattr(pos, "forming", False),
            }
            result["htf_trend"] = getattr(pos, "htf_trend", None)

        # Run divergence search if requested
        if analysis_type == "divergence":
            div_search = DivergenceSearch(
                symbol=candle_data.symbol,
                interval=candle_data.interval,
                data=ohlc,
            )
            div_search.search()
            divergences = div_search.get_results(limit=limit_to)
            if divergences:
                result["divergences"] = {
                    "count": len(divergences),
                    "items": [
                        {
                            "type": getattr(d, "div_type", "unknown"),
                            "symbol": getattr(d, "symbol", candle_data.symbol),
                            "interval": getattr(d, "interval", candle_data.interval),
                        }
                        for d in divergences[:5]
                    ],
                }

        return result

    except AppError:
        raise
    except Exception as e:
        logger.exception("Pattern detection failed for %s", candle_data.symbol)
        raise AppError(
            ErrorCode.DETECTION_ERROR,
            "形态检测失败，请稍后重试。",
            retryable=True,
            original_error=e,
        ) from e


def technical_result_to_schema(
    detection_result: dict,
    signal: Optional[dict] = None,
) -> TechnicalResult:
    """Convert raw detection result to TechnicalResult schema.

    Args:
        detection_result: Raw dict from detect_patterns.
        signal: Optional trade signal dict (from the signal engine).

    Returns:
        TechnicalResult schema instance.
    """
    position = detection_result.get("position")
    patterns = detection_result.get("patterns", {})

    result = TechnicalResult(
        pattern_family=patterns.get("family"),
        pattern_type="forming" if patterns.get("forming") else "formed",
        direction=patterns.get("direction"),
        divergences=detection_result.get("divergences", {}),
        raw_patterns=patterns,
        signal=signal,
    )

    # Unified output contract: when a validated trade signal exists, all
    # actionable fields (direction, family, entry/stop/target/RR) come from it
    # so the top-level result is internally consistent. If the signal engine
    # does not produce a signal (e.g. low confluence score), fall back to the
    # raw pyharmonics Position so the dashboard still shows levels from the
    # detected pattern.
    if signal:
        result.pattern_family = signal.get("family") or patterns.get("family")
        result.pattern_type = "formed" if signal.get("formed") else "forming"
        sig_dir = signal.get("direction")
        result.direction = "bullish" if sig_dir == "long" else "bearish" if sig_dir == "short" else sig_dir
        result.entry_price = signal.get("entry_reference")
        result.stop_loss = signal.get("stop_loss")
        targets = signal.get("targets") or []
        result.target_price = targets[0].get("price") if targets else None
        result.risk_reward_ratio = signal.get("net_rr_tp2")
        result.confidence = "validated-signal"
    elif position:
        # No validated signal, but a harmonic pattern was detected. Surface the
        # raw pyharmonics Position levels so the dashboard still shows actionable
        # info; the confidence flag tells consumers these are unvalidated.
        result.entry_price = float(getattr(position, "strike", 0) or 0) or None
        result.stop_loss = float(getattr(position, "stop", 0) or 0) or None
        targets = getattr(position, "targets", []) or []
        result.target_price = float(targets[0]) if targets else None
        if result.entry_price and result.stop_loss and result.target_price:
            risk = abs(result.entry_price - result.stop_loss)
            reward = abs(result.target_price - result.entry_price)
            result.risk_reward_ratio = round(reward / risk, 4) if risk > 0 else None
        result.confidence = "raw-position"

    return result
