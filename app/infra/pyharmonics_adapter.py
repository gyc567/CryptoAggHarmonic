"""Pyharmonics adapter: wraps all pyharmonics calls and converts exceptions."""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

# Import pyharmonics classes at module level for testability
from pyharmonics.marketdata import YahooCandleData
from pyharmonics.positions import Position
from pyharmonics.search import DivergenceSearch, HarmonicSearch
from pyharmonics.technicals import OHLCTechnicals

from app.api.errors import AppError, ErrorCode
from app.domain.enums import Interval, Market
from app.domain.schemas import TechnicalResult
from app.domain.signals import net_rr
from app.infra import tradingview_adapter as tv
from app.infra.kline_cache import KLineCache, KLineMeta, get_kline_cache
from app.infra.marketdata import DirectBinanceCandleData, DirectBinanceFuturesCandleData

logger = logging.getLogger(__name__)


def _first_target_price(targets: Any) -> Optional[float]:
    """Return the price of the first target, normalizing dict vs float shapes.

    Tolerates the two shapes produced by upstream code:
    - ``Signal.to_dict()["targets"]`` is ``list[{label, price, ...}]``
    - ``pyharmonics.positions.Position.targets`` is ``list[float]``

    Returns None for empty/None inputs and unknown element shapes (defensive).
    """
    if not targets:
        return None
    head = targets[0]
    if isinstance(head, dict):
        return head.get("price")
    if isinstance(head, (int, float)):
        return float(head)
    return None


def _fetch_from_legacy(market: Market, symbol: str, interval: Interval, candles: int) -> Any:
    """Fallback fetcher using Binance spot, Binance futures, or Yahoo."""
    if market == Market.BINANCE:
        cd = DirectBinanceCandleData()
        cd.get_candles(symbol, interval.value, candles)
        return cd
    elif market == Market.FUTURES:
        cd = DirectBinanceFuturesCandleData()
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
    force_refresh: bool = False,
) -> Any:
    """Fetch candle data from market source (with K-line caching).

    TradingView is tried first when enabled and the bridge is healthy; on
    failure we fall back to the legacy Binance/Yahoo adapters so the app
    keeps working even if the bridge is down.

    K-line data is cached using fingerprint-based keys. Cache naturally
    expires when new candles close (fingerprint changes).

    Args:
        market: Market source enum.
        symbol: Uppercase symbol.
        interval: Candle interval.
        candles: Number of candles to fetch.
        force_refresh: Bypass cache and fetch fresh data.

    Returns:
        Candle data object.

    Raises:
        AppError: If market data is unavailable.
    """
    cache = get_kline_cache()
    cache_key = cache.make_key(
        market=market.value,
        symbol=symbol,
        interval=interval.value,
        limit=candles,
    )

    # Try cache first (unless force_refresh)
    if not force_refresh:
        cached_df, cached_meta = cache.get(cache_key)
        if cached_df is not None:
            logger.info(
                "K-line cache hit for %s/%s (%d candles)",
                market.value,
                symbol,
                len(cached_df),
            )
            # Reconstruct CandleData-compatible object from cached DataFrame
            return _df_to_candle_data(cached_df, symbol, interval.value)

    # Fetch from source
    start_time = time.time()
    source_name = "unknown"
    exchange_name = market.value

    if tv.is_tradingview_enabled() and tv.is_bridge_healthy():
        try:
            cd = tv.fetch_market_data(
                market=market.value,
                symbol=symbol,
                interval=interval.value,
                candles=candles,
            )
            source_name = "tradingview"
            exchange_name = market.value
            logger.info(
                "Fetched %s %s from TradingView (%d candles)",
                market.value,
                symbol,
                len(cd.df),
            )
            # Cache the result
            _cache_candle_data(cache, cache_key, cd.df, source_name, exchange_name, start_time)
            return cd
        except Exception as e:
            logger.warning(
                "TradingView fetch failed for %s/%s, falling back: %s",
                market.value,
                symbol,
                e,
            )

    try:
        cd = _fetch_from_legacy(market, symbol, interval, candles)
        source_name = "binance"
        exchange_name = market.value
        logger.info(
            "Fetched %s %s from %s (%d candles)",
            market.value,
            symbol,
            source_name,
            len(cd.df),
        )
        # Cache the result
        _cache_candle_data(cache, cache_key, cd.df, source_name, exchange_name, start_time)
        return cd
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


def _cache_candle_data(
    cache: KLineCache,
    cache_key: str,
    df: Any,
    source: str,
    exchange: str,
    start_time: float,
) -> None:
    """Cache K-line data with metadata."""
    try:
        meta = KLineMeta(
            source=source,
            exchange=exchange,
            symbol="",
            interval="",
            fetched_at=datetime.now(timezone.utc).isoformat(),
            latency_ms=(time.time() - start_time) * 1000,
        )
        cache.set(cache_key, df, meta)
    except Exception as e:
        logger.warning("Failed to cache K-line data: %s", e)


def _df_to_candle_data(df: Any, symbol: str, interval: str) -> Any:
    """Reconstruct CandleData-compatible object from cached DataFrame."""
    # Import here to avoid circular imports
    from pyharmonics.marketdata.candle_base import CandleData

    class CachedCandleData(CandleData):
        SOURCE = "Cache"

        def get_candles(
            self,
            symbol: str,
            interval: str,
            num_candles: Optional[int] = None,
        ) -> None:
            self.symbol = symbol
            self.interval = interval
            self.df = df
            self.num_candles = len(df)
            self.reset_index()

    return CachedCandleData()


class _PatternPosition:
    """Lightweight stand-in for pyharmonics Position with attrs consumers read.

    Derives ``stop`` and ``targets`` from the real ``pyharmonics.positions.Position``
    (whose ``_set_stop`` / ``_set_targets`` know the standard TP ladder) instead of
    guessing nonexistent ``pattern.stop_loss`` / ``pattern.targets`` attributes —
    those were the bug behind "止损价 / 目标价" being None in the dashboard.
    """

    def __init__(self, pattern: Any, symbol: str, interval: str, forming: bool = False, family: Optional[str] = None):
        self.symbol = symbol
        self.interval = interval
        self.forming = forming
        self.pattern = pattern
        self.family = family
        self.strike = self._compute_strike(pattern, family)
        self.stop: Optional[float] = None
        self.targets: list[float] = []
        # Delegate to the real Position so stop/3-TP ladder matches the chart
        # pipeline (which already constructs Position in pyharmonics_handler.py).
        try:
            pos = Position(pattern, strike=self.strike, dollar_amount=100)
            stop = float(pos.stop) if pos.stop is not None else None
            # Clamp non-positive stops (degenerate geometry): schema stop_loss is
            # gt=0 and net_rr requires stop > 0, so a 0/negative stop would
            # violate the contract. Treat it as "no stop" and degrade.
            self.stop = stop if stop and stop > 0 else None
            self.targets = [float(t) for t in (pos.targets or [])]
        except Exception as exc:
            # pyharmonics upgrade / exotic pattern shape — degrade to a minimal
            # position dict; dashboard still shows entry_price + "raw-position-minimal".
            logger.warning("pyharmonics.Position 构造失败，降级到最小 dict: %s", exc)
            self.stop = None
            self.targets = []
        self.reversal = getattr(pattern, "reversal", None)
        bullish = getattr(pattern, "bullish", None)
        explicit_dir = getattr(pattern, "direction", None)
        self.direction = explicit_dir or ("bullish" if bullish else "bearish")
        self.htf_trend = getattr(pattern, "htf_trend", None)

    @staticmethod
    def _compute_strike(pattern: Any, family: Optional[str]) -> float:
        """Pick the entry reference price, family-aware.

        XABCD / ABCD: PRZ midpoint ≈ D (entry zone).
        ABC: completion_max_price = C (no D point exists).

        pyharmonics ``Position._set_targets`` uses ``pattern.y[-2]`` (C point) as
        the A→C reference for the TP ladder, so we must align strike with PRZ
        rather than letting it land on a stale y-index (which would produce
        degenerate TP=strike when ABC's completion_min == completion_max == C).
        """
        try:
            c_min = float(pattern.completion_min_price)
            c_max = float(pattern.completion_max_price)
        except (AttributeError, TypeError, ValueError):
            logger.warning("Pattern %s 缺少 completion_min_price/completion_max_price", pattern)
            return 0.0
        if family == "ABC":
            if c_max > 0:
                return c_max
            logger.warning("ABC pattern completion_max_price 异常: %s", c_max)
            return 0.0
        if c_min > 0 and c_max > 0:
            return (c_min + c_max) / 2.0
        logger.warning("Pattern completion range 异常 (c_min=%s, c_max=%s)", c_min, c_max)
        return 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "strike": self.strike,
            "stop": self.stop,
            "targets": self.targets,
            "direction": self.direction,
            "forming": self.forming,
            "family": self.family,
        }


def detect_patterns(
    candle_data: Any,
    limit_to: int = 10,
    percent_complete: float = 0.8,
    analysis_type: str = "forming",
    fib_tolerance: float = 0.10,
) -> dict:
    """Run harmonic and divergence pattern detection.

    Args:
        candle_data: Candle data object with .df, .symbol, .interval.
        limit_to: Max number of patterns to return.
        percent_complete: Minimum completion ratio (0-1).
        analysis_type: Type of analysis - "forming", "formed", or "divergence".
        fib_tolerance: Fibonacci tolerance for pattern matching (0.10 = looser, finds more patterns).

    Returns:
        Dict with position, patterns, divergences, and HTF trend.
    """
    try:
        ohlc = OHLCTechnicals(candle_data.df, candle_data.symbol, candle_data.interval)
        search = HarmonicSearch(ohlc, fib_tolerance=fib_tolerance)
        div_search = DivergenceSearch(ohlc)

        if analysis_type in ("forming", "auto"):
            search.forming(limit_to=limit_to, percent_c_to_d=percent_complete)
        search.search(limit_to=limit_to)
        div_search.search(limit_to=limit_to)

        formed = search.get_patterns()
        forming = search.get_patterns(formed=False)

        result: dict[str, Any] = {"patterns": {}, "divergences": {}, "position": None}

        pattern = None
        family = None
        is_forming = False
        for fam in (search.XABCD, search.ABCD, search.ABC):
            if formed.get(fam):
                pattern = formed[fam][0]
                family = fam
                break
        if pattern is None:
            for fam in (search.XABCD, search.ABCD, search.ABC):
                if forming.get(fam):
                    pattern = forming[fam][0]
                    family = fam
                    is_forming = True
                    break

        if pattern is not None:
            position = _PatternPosition(pattern, candle_data.symbol, candle_data.interval, forming=is_forming, family=family)
            result["position"] = position
            result["patterns"] = {
                "symbol": candle_data.symbol,
                "family": family,
                "direction": position.direction,
                "entry": position.strike,
                "stop": position.stop,
                "targets": position.targets,
                "reversal": position.reversal,
                "forming": is_forming,
            }
            result["htf_trend"] = position.htf_trend

        div_patterns = div_search.get_patterns()
        div_items = []
        for fam, found in div_patterns.items():
            for pa in found[:limit_to]:
                div_items.append(
                    {
                        "type": getattr(pa, "div_type", fam),
                        "symbol": getattr(pa, "symbol", candle_data.symbol),
                        "interval": getattr(pa, "interval", candle_data.interval),
                    }
                )
        result["divergences"] = {"count": len(div_items), "items": div_items}

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
        result.target_price = _first_target_price(signal.get("targets") or [])
        # Reuse the fee/slippage-aware net_rr from the signal engine rather than
        # rolling our own (it has icontract guarantees + handles fee/slippage).
        if result.entry_price and result.stop_loss and result.target_price:
            result.risk_reward_ratio = net_rr(result.entry_price, result.stop_loss, result.target_price)
        else:
            result.risk_reward_ratio = None
        result.confidence = "validated-signal"
    elif position:
        # No validated signal, but a harmonic pattern was detected. Surface the
        # raw pyharmonics Position levels so the dashboard still shows actionable
        # info; the confidence flag tells consumers these are unvalidated.
        result.entry_price = float(position.strike or 0) or None
        result.stop_loss = float(position.stop or 0) or None
        result.target_price = _first_target_price(getattr(position, "targets", []))
        if result.entry_price and result.stop_loss and result.target_price:
            result.risk_reward_ratio = net_rr(result.entry_price, result.stop_loss, result.target_price)
        else:
            result.risk_reward_ratio = None
        result.confidence = "raw-position"

    return result
