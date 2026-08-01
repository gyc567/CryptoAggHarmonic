"""Unit tests for app.domain.rsi_trend_plan — pure domain logic."""

from __future__ import annotations

import pytest

from app.domain.rsi_trend import LONG, SHORT, StrategySignal
from app.domain.rsi_trend_plan import (
    CONF_W_FRESHNESS,
    CONF_W_QUALITY,
    CONF_W_RSI,
    CONF_W_TREND,
    DEVIATION_WATCH_PCT,
    FRESH_BARS,
    QUALITY_HARD_FLOOR,
    STALE_BARS,
    Decision,
    MarketOverview,
    Target,
    TradingPlan,
    _compute_confidence,
    _compute_trend_strength,
    _serialize,
    build_history_summary,
    build_market_overview,
    compute_position,
    compute_targets,
    evaluate_decision,
)


# ---- trend strength ----------------------------------------------------------


def test_trend_strength_strong_bullish():
    assert _compute_trend_strength(close=200, ema200=150, ema50=180, atr=1.0) == 1.0


def test_trend_strength_entangled_penalty():
    s = _compute_trend_strength(close=152, ema200=150, ema50=148, atr=10.0)
    assert s < 0.5  # entangled because |200-150|=2 < 0.5*10ATR


def test_trend_strength_zero_when_ema200_zero():
    assert _compute_trend_strength(close=100, ema200=0, ema50=110, atr=1.0) == 0.0


def test_trend_strength_no_alignment():
    # close=100, ema200=90, ema50=85 → close > ema200 but NOT close>ema50>ema200 (85<90)
    # alignment=0, deviation = min(10/90, 0.10)=0.10 → 0.5, total=0.5
    s = _compute_trend_strength(close=100, ema200=90, ema50=85, atr=1.0)
    assert s == pytest.approx(0.5)


# ---- market overview ---------------------------------------------------------


def test_market_overview_from_state():
    state = {"trend": "bullish", "close": 68000, "ema200": 64000, "ema50": 65500,
             "deviation_pct": 6.25, "rsi": 58.3, "atr": 1200, "entangled": False}
    ov = build_market_overview(state)
    assert ov.trend == "bullish"
    assert ov.close == 68000
    assert ov.atr_pct == pytest.approx(1.76, rel=0.1)
    assert ov.volatility_regime == "normal"
    assert ov.entangled is False
    assert len(ov.notes) >= 1


def test_market_overview_none():
    ov = build_market_overview(None)
    assert ov.trend == "neutral"


def test_market_overview_entangled_note():
    state = {"trend": "bearish", "close": 100, "ema200": 101, "ema50": 100.5,
             "deviation_pct": -0.99, "rsi": 45, "atr": 3.0, "entangled": True}
    ov = build_market_overview(state)
    assert ov.entangled
    assert any("缠绕" in n for n in ov.notes)


# ---- decision engine ---------------------------------------------------------


def _overview(trend='bullish', deviation=5.0, entangled=False, atr_pct=1.0):
    return MarketOverview(
        trend=trend, trend_strength=0.7, close=68000, ema200=64000,
        deviation_pct=deviation, entangled=entangled,
        atr_pct=atr_pct, volatility_regime="normal" if (atr_pct or 1) < 3 else "high",
    )


def _signal(direction=LONG):
    return {"direction": direction, "entry_price": 68120, "stop_loss": 66200}


def test_decision_trade_fresh_signal():
    d = evaluate_decision(_overview(), _signal(LONG), quality_score=78, signal_age_bars=1)
    assert d.action == "trade"
    assert d.direction == LONG
    assert d.confidence > 0.5


def test_decision_no_trade_null_signal():
    d = evaluate_decision(_overview(), None, quality_score=0, signal_age_bars=999)
    assert d.action == "no_trade"
    assert "无符合条件的入场信号" in str(d.reasons)


def test_decision_no_trade_direction_conflict():
    d = evaluate_decision(_overview(trend='bullish'), _signal(SHORT), quality_score=80, signal_age_bars=1)
    assert d.action == "no_trade"


def test_decision_stale_signal():
    d = evaluate_decision(_overview(), _signal(), quality_score=80, signal_age_bars=20)
    assert d.action == "watch"


def test_decision_low_quality():
    d = evaluate_decision(_overview(), _signal(), quality_score=QUALITY_HARD_FLOOR - 1, signal_age_bars=1)
    assert d.action == "no_trade"


def test_decision_high_deviation():
    d = evaluate_decision(_overview(deviation=DEVIATION_WATCH_PCT + 1), _signal(), quality_score=80, signal_age_bars=1)
    assert d.action == "watch"


def test_decision_entangled():
    d = evaluate_decision(_overview(entangled=True), _signal(), quality_score=80, signal_age_bars=1)
    assert d.action == "watch"


def test_decision_high_volatility_warning():
    d = evaluate_decision(_overview(atr_pct=4.0), _signal(), quality_score=80, signal_age_bars=1)
    assert d.action == "trade"
    assert any("波动率" in w for w in d.warnings)


def test_decision_stale_but_fresh_warning():
    d = evaluate_decision(_overview(), _signal(), quality_score=80, signal_age_bars=5)
    assert d.action == "trade"
    assert any("距今" in w for w in d.warnings)


# ---- targets -----------------------------------------------------------------


def test_compute_targets_long():
    targets = compute_targets(entry=100, stop=90, direction=LONG)
    assert len(targets) == 3
    assert targets[0].level == "tp1"
    assert targets[0].price > 100
    assert targets[2].price > targets[1].price > targets[0].price


def test_compute_targets_short():
    targets = compute_targets(entry=100, stop=110, direction=SHORT)
    assert len(targets) == 3
    assert targets[0].price < 100
    assert targets[2].price < targets[1].price < targets[0].price


def test_compute_targets_zero_risk():
    assert compute_targets(entry=100, stop=100, direction=LONG) == []


# ---- position ----------------------------------------------------------------


def test_compute_position_normal():
    p = compute_position(entry=68000, stop=66200, direction=LONG,
                         total_capital_wu=100_000, risk_appetite="balanced",
                         volatility_regime="normal")
    assert p.configured is True
    assert p.risk_per_trade_pct == pytest.approx(1.0)
    assert p.position_size_wu > 0
    assert p.position_size_u > 0


def test_compute_position_high_vol():
    p = compute_position(entry=68000, stop=66200, direction=LONG,
                         total_capital_wu=100_000, risk_appetite="balanced",
                         volatility_regime="high")
    assert "0.5" in p.sizing_note


def test_compute_position_conservative():
    p = compute_position(entry=68000, stop=66200, direction=LONG,
                         total_capital_wu=100_000, risk_appetite="conservative",
                         volatility_regime="normal")
    assert p.risk_per_trade_pct == pytest.approx(0.5)


def test_compute_position_zero_risk():
    p = compute_position(entry=100, stop=100, direction=LONG,
                         total_capital_wu=100_000, risk_appetite="balanced",
                         volatility_regime="normal")
    assert p.configured is False


# ---- confidence --------------------------------------------------------------


def test_confidence_components():
    c = _compute_confidence(trend_strength=0.8, quality_score=80, signal_age_bars=1)
    expected = CONF_W_TREND * 0.8 + CONF_W_QUALITY * 0.8 + CONF_W_RSI * 0.7 + CONF_W_FRESHNESS * (1 - 1 / (STALE_BARS * 2))
    assert c == pytest.approx(expected)


def test_confidence_clamped():
    c = _compute_confidence(trend_strength=1.0, quality_score=100, signal_age_bars=0)
    assert c <= 1.0


# ---- history -----------------------------------------------------------------


def test_history_empty():
    h = build_history_summary([])
    assert h["signals_count"] == 0


def test_history_with_signals():
    s1 = StrategySignal(direction=LONG, entry_price=100, stop_loss=90, target_price=110,
                        atr=1.0, rsi=40.0, time="2026-01-01", index=0, quality_score=60)
    s2 = StrategySignal(direction=SHORT, entry_price=100, stop_loss=110, target_price=90,
                        atr=1.0, rsi=60.0, time="2026-01-02", index=1, quality_score=70)
    h = build_history_summary([s1, s2])
    assert h["signals_count"] == 2
    assert h["longs"] == 1
    assert h["shorts"] == 1


# ---- serialization -----------------------------------------------------------


def test_tradingplan_to_dict():
    tp = TradingPlan(symbol="BTCUSDT", interval="4h")
    d = tp.to_dict()
    assert d["symbol"] == "BTCUSDT"
    assert d["plan_non_prod"] is True
    assert "market_overview" in d
    assert d["market_overview"]["trend"] == "neutral"


def test_serialize_nested_dataclass():
    tp = TradingPlan()
    tp.market_overview = MarketOverview(trend="bullish", close=100, ema200=90, ema50=95)
    d = _serialize(tp)
    assert d["market_overview"]["trend"] == "bullish"
