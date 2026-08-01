"""TradingPlan data structure and decision engine for RSI trend strategy.

Pure domain logic — no I/O, no framework dependencies.  All functions
accept plain Python types and return dataclass instances or dicts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.domain.rsi_trend import LONG, SHORT, StrategySignal

# ---- constants (alpha — to be calibrated via backtest) -----------------------

DEVIATION_WATCH_PCT = 15.0      # |deviation| above this → watch (chase risk)
FRESH_BARS = 3                  # <= this many bars old → fresh signal
STALE_BARS = 12                 # > this → no trade
QUALITY_HARD_FLOOR = 50.0       # below this → no_trade regardless of filters
ATR_LOW_PCT = 0.8               # ATR / close < this → low vol
ATR_HIGH_PCT = 3.0              # ATR / close > this → high vol
VOLATILITY_SIZE_REDUCTION = 0.5 # position size multiplier in high vol

# Confidence weights (sum = 1.0)
CONF_W_TREND = 0.35
CONF_W_QUALITY = 0.30
CONF_W_RSI = 0.20
CONF_W_FRESHNESS = 0.15

# Target weight distribution (sum = 1.0)
TP1_WEIGHT = 0.50
TP2_WEIGHT = 0.30
TP3_WEIGHT = 0.20

# Multiplier on risk for each target
TP1_RISK_MULT = 1.0
TP2_RISK_MULT = 2.0
TP3_RISK_MULT = 3.5

# Risk per trade % by appetite
RISK_BY_APPETITE = {
    "conservative": 0.005,
    "balanced": 0.01,
    "aggressive": 0.015,
}
DEFAULT_RISK_PCT = 0.01

WU_UNIT = 10_000  # 1 U = 10,000 WU


# ---- data classes ------------------------------------------------------------


@dataclass
class EntryPlan:
    price: float
    trigger: str
    entry_type: str = "market"


@dataclass
class StopPlan:
    price: float
    logic: str
    distance_atr: float


@dataclass
class Target:
    level: str
    price: float
    rr: float
    weight: float


@dataclass
class PositionPlan:
    risk_per_trade_pct: Optional[float] = None
    total_capital_wu: Optional[float] = None
    risk_amount_wu: Optional[float] = None
    position_size_wu: Optional[float] = None
    position_size_u: Optional[float] = None
    sizing_note: str = ""
    configured: bool = False


@dataclass
class ManagementPlan:
    breakeven_after: str = "tp1"
    trailing_stop: bool = True
    time_stop: str = ""


@dataclass
class MarketOverview:
    trend: str = "neutral"
    trend_strength: float = 0.0
    close: float = 0.0
    ema200: float = 0.0
    ema50: float = 0.0
    deviation_pct: float = 0.0
    rsi: Optional[float] = None
    atr: Optional[float] = None
    atr_pct: Optional[float] = None
    volatility_regime: str = "normal"
    entangled: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class Decision:
    action: str = "no_trade"       # trade / watch / no_trade
    direction: Optional[str] = None  # long / short / None
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    watch_for: Optional[str] = None  # populated when action=watch


@dataclass
class TradingPlan:
    symbol: str = ""
    interval: str = "4h"
    generated_at: str = ""
    plan_non_prod: bool = True

    market_overview: MarketOverview = field(default_factory=MarketOverview)
    decision: Decision = field(default_factory=Decision)
    plan: Optional[dict] = None            # entry/stop/targets/position/management
    multi_tf: Any = None                    # phase 2 — always None in v1
    invalidation: list[str] = field(default_factory=list)
    history: Optional[dict] = None          # signal history summary
    ai_insight: Optional[dict] = None       # LLM summary (null when skipped/failed)

    def to_dict(self) -> dict:
        """Serialize to the API response dict (frontend TS contract)."""
        return _serialize(self)


# ---- pure domain functions ---------------------------------------------------


def build_market_overview(state: dict | None) -> MarketOverview:
    """Build market overview from `current_state()` output."""
    if state is None:
        return MarketOverview()
    close = state.get("close", 0.0) or 0.0
    ema200 = state.get("ema200", 0.0) or 0.0
    rsi = state.get("rsi")
    atr = state.get("atr")

    overview = MarketOverview(
        trend=state.get("trend", "neutral") or "neutral",
        trend_strength=_compute_trend_strength(close, ema200, state.get("ema50", 0.0) or 0.0, atr),
        close=close,
        ema200=ema200,
        ema50=state.get("ema50", 0.0) or 0.0,
        deviation_pct=state.get("deviation_pct", 0.0) or 0.0,
        rsi=rsi,
        atr=atr,
        atr_pct=round((atr / close * 100), 2) if atr and close else None,
        volatility_regime=_volatility_regime(atr, close),
        entangled=bool(state.get("entangled", False)),
    )

    # descriptive notes
    notes = []
    t = overview.trend
    if t in ("bullish", "bearish"):
        notes.append(f"价格站{'上' if t == 'bullish' else '下'} EMA200，趋势{'多头' if t == 'bullish' else '空头'}")
    elif t == "neutral":
        notes.append("价格紧贴 EMA200，趋势方向不明")
    if overview.deviation_pct and abs(overview.deviation_pct) > 10:
        notes.append(f"偏离 EMA200 超过 {abs(overview.deviation_pct):.0f}%，追高风险加剧")
    if overview.entangled:
        notes.append("EMA50 与 EMA200 缠绕，横盘震荡特征明显")
    overview.notes = notes
    return overview


def evaluate_decision(
    overview: MarketOverview,
    latest_signal: Optional[dict],
    quality_score: float = 0.0,
    signal_age_bars: int = 999,
) -> Decision:
    """Pure 4-layer decision engine.

    Returns a Decision that tells the caller what to do — and why.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    # ── L1: trend filter ──────────────────────────────────
    trend = overview.trend
    # L1.trend: current_state() returns "bullish" / "bearish", map to "long" / "short"
    if trend == "bullish":
        direction = LONG
    elif trend == "bearish":
        direction = SHORT
    else:
        return Decision(action="watch", reasons=[f"趋势中性 ({overview.trend})，等待方向确认"],
                        watch_for="等待价格明确突破 EMA200 上方或下方")

    if abs(overview.deviation_pct) >= DEVIATION_WATCH_PCT:
        reasons.append(f"偏离 EMA200 {overview.deviation_pct:.0f}%，追高风险")
        return Decision(action="watch", direction=direction, reasons=reasons,
                        watch_for=f"等待回调至 EMA200 附近（当前偏离 {overview.deviation_pct:.1f}%）")

    if overview.entangled:
        return Decision(action="watch", direction=direction,
                        reasons=["EMA50/200 缠绕，方向不明朗"],
                        watch_for="等待 EMA50 与 EMA200 重新展开（不再缠绕）")

    # ── L2: momentum trigger ──────────────────────────────
    if latest_signal is None:
        return Decision(action="no_trade", reasons=[f"最近 {STALE_BARS} 根K线内无符合条件的入场信号"],
                        watch_for="等待 RSI 进入超卖/回调区并形成顺势穿越信号")

    signal_dir = latest_signal.get("direction")
    if signal_dir and signal_dir != direction:
        return Decision(action="no_trade", reasons=[f"最新信号方向({signal_dir})与趋势方向({trend})冲突"])

    if signal_age_bars > STALE_BARS:
        reasons.append(f"最新信号已过去 {signal_age_bars} 根K线，已陈旧")
        return Decision(action="watch", direction=direction, reasons=reasons,
                        watch_for="等待新的 RSI 穿越信号")

    if signal_age_bars > FRESH_BARS:
        warnings.append(f"信号距今 {signal_age_bars} 根K线，价格可能已走出预期范围")

    # ── L3: quality filter ────────────────────────────────
    if quality_score < QUALITY_HARD_FLOOR:
        reasons.append(f"质量分 {quality_score:.0f} 低于硬性阈值 {QUALITY_HARD_FLOOR}")
        return Decision(action="no_trade", reasons=reasons)

    reasons.append(f"信号质量分 {quality_score:.0f}，通过质量过滤")
    reasons.append(f"RSI 穿越触发超{'卖' if direction == 'long' else '买'}反转信号")
    reasons.append(f"价格位于 EMA200 {'上' if direction == 'long' else '下'}方，顺势{'做' + ('多' if direction == 'long' else '空')}")

    # ── L4: volatility check ──────────────────────────────
    if overview.volatility_regime == "high":
        warnings.append(f"ATR 占价格 {overview.atr_pct:.1f}%，波动率偏高，建议仓位减半")

    # ── confidence ────────────────────────────────────────
    confidence = _compute_confidence(
        overview.trend_strength,
        quality_score,
        signal_age_bars,
    )

    return Decision(
        action="trade",
        direction=direction,
        confidence=round(confidence, 2),
        reasons=reasons,
        warnings=warnings,
    )


def compute_targets(entry: float, stop: float, direction: str) -> list[Target]:
    """Generate 3-tier target list from entry and stop."""
    risk = abs(entry - stop)
    if risk <= 0:
        return []
    sign = 1 if direction == LONG else -1
    return [
        Target("tp1", round(entry + sign * risk * TP1_RISK_MULT, 8), round(TP1_RISK_MULT, 2), TP1_WEIGHT),
        Target("tp2", round(entry + sign * risk * TP2_RISK_MULT, 8), round(TP2_RISK_MULT, 2), TP2_WEIGHT),
        Target("tp3", round(entry + sign * risk * TP3_RISK_MULT, 8), round(TP3_RISK_MULT, 2), TP3_WEIGHT),
    ]


def compute_position(
    entry: float, stop: float, direction: str,
    total_capital_wu: float, risk_appetite: str,
    volatility_regime: str,
) -> PositionPlan:
    """Compute position size in WU/U from capital and risk appetite."""
    risk_pct = RISK_BY_APPETITE.get(risk_appetite, DEFAULT_RISK_PCT)
    risk_amount_wu = total_capital_wu * risk_pct
    risk_per_unit = abs(entry - stop) / entry
    if risk_per_unit <= 0:
        return PositionPlan(risk_per_trade_pct=risk_pct, configured=False)

    size_wu = risk_amount_wu / risk_per_unit
    note = ""
    if volatility_regime == "high":
        size_wu *= VOLATILITY_SIZE_REDUCTION
        note = "波动率偏高，已按 0.5 系数减仓"

    return PositionPlan(
        risk_per_trade_pct=round(risk_pct * 100, 2),
        total_capital_wu=total_capital_wu,
        risk_amount_wu=round(risk_amount_wu, 2),
        position_size_wu=round(size_wu, 2),
        position_size_u=round(size_wu / WU_UNIT, 4),
        sizing_note=note,
        configured=True,
    )


def build_history_summary(signals: list[StrategySignal]) -> dict:
    """Build a lightweight history summary from recent detected signals."""
    n = len(signals)
    if n == 0:
        return {"signals_count": 0, "note": "最近数据中无历史信号"}
    longs = sum(1 for s in signals if s.direction == LONG)
    return {
        "signals_count": n,
        "longs": longs,
        "shorts": n - longs,
        "avg_quality": round(sum(s.quality_score for s in signals) / n, 1) if n > 0 else 0,
        "note": (
            "⚠️ 历史信号取自与当前分析相同的 K 线窗口——不构成未来预测。"
            if n < 20 else
            f"近 500 根K线检测到 {n} 个交易信号"
        ),
    }


# ---- internal helpers --------------------------------------------------------


def _compute_trend_strength(close: float, ema200: float, ema50: float, atr: Optional[float]) -> float:
    """0-1 score: how strong and clear the trend is."""
    if ema200 <= 0 or close <= 0:
        return 0.0
    # alignment: 0.5 if EMA cascade matches direction
    alignment = 0.5 if ((close > ema50 > ema200) or (close < ema50 < ema200)) else 0.0
    # deviation strength: capped at 10%
    deviation = min(abs((close - ema200) / ema200), 0.10)
    strength = (deviation / 0.10) * 0.5
    # entangled penalty
    if atr and abs(close - ema200) < 0.5 * atr:
        strength *= 0.4
    return round(min(alignment + strength, 1.0), 2)


def _volatility_regime(atr: Optional[float], close: float) -> str:
    if atr is None or close <= 0:
        return "normal"
    pct = atr / close * 100
    if pct < ATR_LOW_PCT:
        return "low"
    if pct > ATR_HIGH_PCT:
        return "high"
    return "normal"


def _compute_confidence(
    trend_strength: float,
    quality_score: float,
    signal_age_bars: int,
) -> float:
    """0–1 confidence from weighted sub-scores."""
    qs = quality_score / 100.0
    freshness = max(0.0, 1.0 - signal_age_bars / (STALE_BARS * 2))
    rsi_momentum = 0.7  # default — only meaningful when RSI crossing zone
    conf = (
        CONF_W_TREND * trend_strength
        + CONF_W_QUALITY * qs
        + CONF_W_RSI * rsi_momentum
        + CONF_W_FRESHNESS * freshness
    )
    return min(max(conf, 0.0), 1.0)


def _serialize(obj: Any) -> Any:
    """Recursively convert dataclasses to dicts."""
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        result: dict[str, Any] = {}
        for f_name, f_def in obj.__dataclass_fields__.items():
            val = getattr(obj, f_name)
            result[f_name] = _serialize(val)
        return result
    return str(obj)
