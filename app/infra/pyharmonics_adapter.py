"""Pyharmonics adapter: wraps all pyharmonics calls and converts exceptions."""

import logging
from typing import Any, Optional

# Import pyharmonics classes at module level for testability
from pyharmonics.marketdata import YahooCandleData
from pyharmonics.plotter import HarmonicPlotter, PositionPlotter
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
        limit_to: Pattern limit.
        percent_complete: Formation completion ratio.
        analysis_type: Type of analysis (forming/formed/divergence).

    Returns:
        Dict with technical results including patterns, divergences, position.

    Raises:
        AppError: If detection fails.
    """
    try:
        t = OHLCTechnicals(candle_data.df, candle_data.symbol, candle_data.interval)
        hs = HarmonicSearch(t)
        d = DivergenceSearch(t)
        p = HarmonicPlotter(t)

        # "auto" runs the full pipeline, same as an explicit "forming" request;
        # "formed"/"divergence" skip the forming scan to save compute.
        if analysis_type in ("forming", "auto"):
            hs.forming(limit_to=limit_to, percent_c_to_d=percent_complete)
        hs.search(limit_to=limit_to)
        d.search(limit_to=limit_to)

        p.add_peaks()
        p.add_harmonic_plots(hs.get_patterns(family=hs.XABCD))
        p.add_harmonic_plots(hs.get_patterns(family=hs.ABCD))
        p.add_harmonic_plots(hs.get_patterns(family=hs.ABC))
        p.add_divergence_plots(d.get_patterns())

        # Extract patterns
        assessment = {
            "forming": hs.get_patterns(formed=False),
            "patterns": hs.get_patterns(),
        }

        divergences = {family: [pa.to_dict() for pa in found[-1:]] for family, found in d.get_patterns().items()}

        result = {
            "divergences": divergences,
            "patterns": {},
            "position": None,
            "plot": None,
            "raw_assessment": assessment,
        }

        # Find best pattern
        pattern = None
        if assessment["patterns"].get(hs.XABCD):
            pattern = assessment["patterns"][hs.XABCD][0]
            result["patterns"]["family"] = "XABCD"
        elif assessment["patterns"].get(hs.ABCD):
            pattern = assessment["patterns"][hs.ABCD][0]
            result["patterns"]["family"] = "ABCD"
        elif assessment["patterns"].get(hs.ABC):
            pattern = assessment["patterns"][hs.ABC][0]
            result["patterns"]["family"] = "ABC"
        elif assessment["forming"].get(hs.XABCD):
            pattern = assessment["forming"][hs.XABCD][0]
            result["patterns"]["family"] = "XABCD"
            result["patterns"]["forming"] = True
        elif assessment["forming"].get(hs.ABCD):
            pattern = assessment["forming"][hs.ABCD][0]
            result["patterns"]["family"] = "ABCD"
            result["patterns"]["forming"] = True
        elif assessment["forming"].get(hs.ABC):
            pattern = assessment["forming"][hs.ABC][0]
            result["patterns"]["family"] = "ABC"
            result["patterns"]["forming"] = True

        if pattern:
            strike = (pattern.completion_min_price + pattern.completion_max_price) / 2
            position = Position(pattern, strike=strike, dollar_amount=100)
            pos_plot = PositionPlotter(t, position)
            pos_plot.add_divergence_plots(d.get_patterns())
            result["position"] = position
            result["plot"] = pos_plot
            # Prefer explicit direction if present; otherwise map pyharmonics'
            # `bullish` boolean to a canonical direction string.
            explicit_dir = getattr(pattern, "direction", None)
            if explicit_dir:
                result["patterns"]["direction"] = explicit_dir
            else:
                result["patterns"]["direction"] = "bullish" if getattr(pattern, "bullish", None) else "bearish"
            result["patterns"]["completion_min"] = getattr(pattern, "completion_min_price", None)
            result["patterns"]["completion_max"] = getattr(pattern, "completion_max_price", None)
            result["patterns"]["pattern_name"] = getattr(pattern, "name", None)

        result["plot_fallback"] = p
        return result

    except AppError:
        raise
    except Exception as e:
        logger.exception("Pattern detection failed")
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "形态检测过程中发生错误。",
            retryable=True,
            original_error=e,
        ) from e


def render_chart(
    detection_result: dict,
    dpi: int = 150,
) -> tuple:
    """Render the detection plot to PNG bytes in a single pass.

    Kaleido serializes figures with orjson, which cannot handle pandas
    Timestamps (our dts column). The figure is therefore sanitized through
    plotly's own JSON encoder (Timestamps -> ISO strings) before rendering.

    Args:
        detection_result: Result from detect_patterns.
        dpi: DPI for chart rendering.

    Returns:
        Tuple of (compressed PNG bytes, ChartMeta).

    Raises:
        AppError: If chart generation fails.
    """
    import plotly.io as pio

    from app.services.chart import compress_chart

    try:
        plot = detection_result.get("plot") or detection_result.get("plot_fallback")
        if plot is None:
            raise AppError(
                ErrorCode.CHART_ERROR,
                "No plot data available for chart generation.",
            )

        safe_fig = pio.from_json(pio.to_json(plot.main_plot))
        image_bytes = pio.to_image(safe_fig, width=4 * dpi, height=2 * dpi, scale=1)
        if not image_bytes:
            raise AppError(
                ErrorCode.CHART_ERROR,
                "Chart rendering returned empty data.",
            )

        return compress_chart(image_bytes)

    except AppError:
        raise
    except Exception as e:
        logger.exception("Chart generation failed")
        raise AppError(
            ErrorCode.CHART_ERROR,
            "图表生成失败，结构化结果仍可查看。",
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
