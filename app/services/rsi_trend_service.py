"""Orchestration service for the trend-RSI strategy.

Thin layer between the API blueprint and the pure domain logic in
``app.domain.rsi_trend`` / ``app.domain.rsi_trend_backtest``. All market
data access happens here, reusing the existing infra adapters unchanged.
"""
from __future__ import annotations

import logging

from app.api.errors import AppError
from app.domain.enums import ErrorCode, Interval, Market
from app.domain.rsi_trend import WARMUP_BARS, current_state, detect_signals
from app.domain.rsi_trend_backtest import run_backtest
from app.domain.rsi_trend_schemas import RsiTrendBacktestRequest, RsiTrendScanRequest
from app.infra.historical_data import fetch_historical_data
from app.infra.pyharmonics_adapter import fetch_market_data

logger = logging.getLogger(__name__)

SCAN_CANDLES = 500
RECENT_SIGNALS_LIMIT = 10


def _require_enough_bars(rows: int, symbol: str) -> None:
    if rows <= WARMUP_BARS:
        raise AppError(
            ErrorCode.INVALID_PARAMS,
            f"{symbol} 可用K线不足（{rows} 根），EMA200 策略至少需要 {WARMUP_BARS + 1} 根",
        )


def scan(req: RsiTrendScanRequest) -> dict:
    """Current trend/momentum state plus the most recent entry signals."""
    candle_data = fetch_market_data(
        market=Market(req.market),
        symbol=req.symbol.upper(),
        interval=Interval(req.interval),
        candles=SCAN_CANDLES,
    )
    df = candle_data.df
    if df is None or df.empty:
        raise AppError(
            ErrorCode.MARKET_DATA_UNAVAILABLE,
            f"无法获取 {req.symbol} {req.interval} 行情数据",
            retryable=True,
        )
    _require_enough_bars(len(df), req.symbol)

    state = current_state(df)
    signals = detect_signals(
        df,
        use_ema50=req.use_ema50,
        require_candle_color=req.require_candle_color,
        atr_mult=req.atr_mult,
        rsi_zone=req.rsi_zone,
        reward_risk=req.reward_risk,
        min_quality_score=req.min_quality_score,
    )
    recent = [s.to_dict() for s in signals[-RECENT_SIGNALS_LIMIT:]][::-1]
    latest = recent[0] if recent else None
    return {
        "market": req.market,
        "symbol": req.symbol.upper(),
        "interval": req.interval,
        "filters": {
            "use_ema50": req.use_ema50,
            "require_candle_color": req.require_candle_color,
            "atr_mult": req.atr_mult,
            "rsi_zone": req.rsi_zone,
            "reward_risk": req.reward_risk,
            "min_quality_score": req.min_quality_score,
        },
        "bars": len(df),
        "state": state,
        "latest_signal": latest,
        "recent_signals": recent,
    }


def backtest(req: RsiTrendBacktestRequest) -> dict:
    """Full strategy backtest over a historical window."""
    try:
        df = fetch_historical_data(
            market=req.market,
            symbol=req.symbol,
            interval=req.interval,
            lookback_days=req.lookback_days,
        )
    except ValueError as e:
        raise AppError(ErrorCode.INVALID_PARAMS, str(e))
    except RuntimeError as e:
        raise AppError(ErrorCode.MARKET_DATA_UNAVAILABLE, str(e), retryable=True)
    if df is None or df.empty:
        raise AppError(
            ErrorCode.MARKET_DATA_UNAVAILABLE,
            f"无法获取 {req.symbol} {req.interval} 历史数据",
            retryable=True,
        )
    _require_enough_bars(len(df), req.symbol)

    signals = detect_signals(
        df,
        use_ema50=req.use_ema50,
        require_candle_color=req.require_candle_color,
        atr_mult=req.atr_mult,
        rsi_zone=req.rsi_zone,
        reward_risk=req.reward_risk,
        min_quality_score=req.min_quality_score,
    )
    result = run_backtest(df, signals, partial_mode=req.partial_mode, trailing_stop=req.trailing_stop)
    return {
        "market": req.market,
        "symbol": req.symbol.upper(),
        "interval": req.interval,
        "lookback_days": req.lookback_days,
        "filters": {
            "use_ema50": req.use_ema50,
            "require_candle_color": req.require_candle_color,
            "atr_mult": req.atr_mult,
            "rsi_zone": req.rsi_zone,
            "reward_risk": req.reward_risk,
            "min_quality_score": req.min_quality_score,
            "partial_mode": req.partial_mode,
            "trailing_stop": req.trailing_stop,
        },
        "bars": len(df),
        **result.to_dict(),
    }
