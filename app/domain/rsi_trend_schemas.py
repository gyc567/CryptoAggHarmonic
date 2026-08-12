"""Pydantic request schemas for the trend-RSI strategy API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

CRYPTO_INTERVALS = ("1h", "4h", "1d")
STOCK_INTERVALS = ("1d", "1w")


class RsiTrendScanRequest(BaseModel):
    """Parameters shared by the scan and backtest endpoints."""

    market: Literal["binance", "yahoo"] = "binance"
    symbol: str = Field(min_length=1, max_length=30)
    interval: Literal["1h", "4h", "1d", "1w"] = "4h"
    use_ema50: bool = False
    require_candle_color: bool = False
    atr_mult: float = Field(default=1.0, ge=0.5, le=3.0)
    rsi_zone: Literal["extreme", "pullback"] = "extreme"
    reward_risk: float = Field(default=2.0, ge=1.0, le=5.0)
    min_quality_score: float = Field(default=0.0, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def _check_market_interval(self):
        # Yahoo has no continuous 4H session for stocks; restrict intervals.
        if self.market == "yahoo" and self.interval not in STOCK_INTERVALS:
            raise ValueError(f"股票市场(yahoo)仅支持周期: {', '.join(STOCK_INTERVALS)}")
        if self.market == "binance" and self.interval not in CRYPTO_INTERVALS:
            raise ValueError(f"加密货币(binance)仅支持周期: {', '.join(CRYPTO_INTERVALS)}")
        return self


class RsiTrendBacktestRequest(RsiTrendScanRequest):
    """Backtest endpoint parameters."""

    lookback_days: int = Field(default=180, ge=60, le=365)
    partial_mode: bool = False
    trailing_stop: bool = False
    exit_ema: Literal["ema200", "ema50"] = "ema200"
    ttl_bars: int = Field(default=0, ge=0, le=200, description="Circuit-breaker: exit after N bars (0=off)")
    short_rsi_min: float = Field(default=0.0, ge=0.0, le=80.0, description="Short RSI_prev minimum threshold (0=off)")
