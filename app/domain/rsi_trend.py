"""
rsi_trend — backward-compatible API wrapper.

All signal-detection logic lives in ``strategy_core``.
This module provides backward-compatible exports for existing callers.

New code should import directly from ``strategy_core``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import pandas as pd

# Re-export everything from strategy_core so existing imports still work.
from app.domain.strategy_core import (  # noqa: F401, F403
    RSI_WINDOW,
    ATR_WINDOW,
    EMA_TREND_SPAN,
    EMA_FAST_SPAN,
    OVERSOLD,
    OVERBOUGHT,
    PULLBACK_OVERSOLD,
    PULLBACK_OVERBOUGHT,
    REWARD_RISK,
    WARMUP_BARS,
    RSI_ZONES,
    LONG,
    SHORT,
    Signal,
    compute_indicators,
    detect_signals_core,
    current_state_core,
    signal_quality as _signal_quality,
)

# ---------------------------------------------------------------------------
# Backward-compatible aliases
# ---------------------------------------------------------------------------

#: Alias for ``compute_indicators``.
enrich = compute_indicators


# ---------------------------------------------------------------------------
# StrategySignal — legacy wrapper around strategy_core.Signal
# ---------------------------------------------------------------------------

@dataclass
class StrategySignal:
    """Legacy signal type used by the API service layer."""

    direction: str
    entry_price: float
    stop_loss: float
    target_price: float
    atr: float
    rsi: float
    time: str
    index: int
    quality_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# detect_signals — wraps strategy_core.detect_signals_core
# ---------------------------------------------------------------------------

def detect_signals(
    df: pd.DataFrame,
    *,
    use_ema50: bool = False,
    require_candle_color: bool = False,
    atr_mult: float = 1.0,
    rsi_zone: str = "extreme",
    reward_risk: float = REWARD_RISK,
    min_quality_score: float = 0.0,
    short_rsi_min: float = 65.0,
) -> list[StrategySignal]:
    """
    Scan ``df`` for entry signals.

    Legacy wrapper around ``detect_signals_core`` that converts
    ``Signal`` → ``StrategySignal`` for API compatibility.

    See ``strategy_core.detect_signals_core`` for full parameter docs.
    """
    signals = detect_signals_core(
        df,
        use_ema50=use_ema50,
        require_candle_color=require_candle_color,
        atr_mult=atr_mult,
        rsi_zone=rsi_zone,
        reward_risk=reward_risk,
        min_quality_score=min_quality_score,
        short_rsi_min=short_rsi_min,
    )
    return [
        StrategySignal(
            direction=s.direction,
            entry_price=s.entry_price,
            stop_loss=s.stop_loss,
            target_price=s.target_price,
            atr=s.atr,
            rsi=s.rsi,
            time=s.time,
            index=s.index,
            quality_score=s.quality_score,
        )
        for s in signals
    ]


# ---------------------------------------------------------------------------
# current_state — wraps strategy_core.current_state_core
# ---------------------------------------------------------------------------

def current_state(df: pd.DataFrame) -> dict | None:
    """
    Latest trend/momentum snapshot.

    Wraps ``strategy_core.current_state_core``.
    """
    return current_state_core(df)
