"""Build a TradingPlan from RSI trend data.

Orchestrates: scan → decision → targets → position → AI insight.
Thin layer — all I/O is delegated to existing services.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.domain.rsi_trend import LONG, SHORT
from app.domain.rsi_trend_plan import (
    Decision,
    PositionPlan,
    TradingPlan,
    build_history_summary,
    build_market_overview,
    compute_position,
    compute_targets,
    evaluate_decision,
)
from app.domain.rsi_trend_schemas import RsiTrendScanRequest
from app.services.llm_client import complete as llm_complete
from app.services.position_reader import get_position_config
from app.services.rsi_trend_service import PLAN_CANDLES, _scan_core

logger = logging.getLogger(__name__)

# Simple in-process cache: {cache_key: ai_insight_dict}
_AI_CACHE: dict[str, dict] = {}


def build_plan(req: RsiTrendScanRequest, user_id: str) -> dict:
    """Run the full analysis pipeline and return a TradingPlan dict."""

    core = _scan_core(req, candles=PLAN_CANDLES)

    # 1. market overview
    overview = build_market_overview(core.state)

    # 2. decision — use most recent signal (core.signals is oldest-first)
    latest_signal: Optional[dict] = None
    quality_score = 0.0
    signal_age_bars = 999
    if core.signals:
        best = core.signals[-1]  # most recent
        latest_signal = best.to_dict()
        quality_score = best.quality_score
        signal_age_bars = len(core.df) - 1 - best.index
        if signal_age_bars < 0:
            signal_age_bars = 0

    decision = evaluate_decision(overview, latest_signal, quality_score, signal_age_bars)

    # 3. plan (only when action=trade)
    plan_dict: Optional[dict] = None
    invalidation: list[str] = []
    if decision.action == "trade" and latest_signal:
        entry = latest_signal.get("entry_price", 0.0) or 0.0
        stop = latest_signal.get("stop_loss", 0.0) or 0.0
        direction = decision.direction or ""
        atr = latest_signal.get("atr", 1.0) or 1.0

        targets = compute_targets(entry, stop, direction)
        weighted_rr = round(sum(t.rr * t.weight for t in targets), 2) if targets else 0
        position = _load_position(user_id, entry, stop, direction, overview.volatility_regime)

        plan_dict = {
            "entry": {
                "price": entry,
                "trigger": (
                    "现价挂单或回踩 EMA 附近分批入场" if direction == LONG
                    else "现价挂单或反弹至 EMA 附近分批入场"
                ),
                "entry_type": "market",
            },
            "stop": {
                "price": stop,
                "logic": f"信号K线{'低' if direction == LONG else '高'}点 - ATR 止损",
                "distance_atr": round(abs(entry - stop) / atr, 2) if atr else 0,
            },
            "targets": [
                {"level": t.level, "price": t.price, "rr": t.rr, "weight": t.weight}
                for t in targets
            ],
            "risk_reward": weighted_rr,
            "position": {
                "risk_per_trade_pct": position.risk_per_trade_pct,
                "total_capital_wu": position.total_capital_wu,
                "risk_amount_wu": position.risk_amount_wu,
                "position_size_wu": position.position_size_wu,
                "position_size_u": position.position_size_u,
                "sizing_note": position.sizing_note,
                "configured": position.configured,
            },
            "management": {
                "breakeven_after": "tp1",
                "trailing_stop": True,
                "time_stop": _time_stop(req.interval or "4h"),
            },
        }

        invalidation = [
            _invalidation_trend(direction, overview.ema200),
            _invalidation_stop(direction, stop),
            _invalidation_signal(direction),
        ]

    # 4. history
    history = build_history_summary(core.signals)

    # 5. AI insight (cached per bar, only for trade/watch)
    ai_insight = None
    if decision.action in ("trade", "watch"):
        ai_insight = _ai_insight(overview, decision, plan_dict, req)

    # 6. assemble
    plan = TradingPlan(
        symbol=req.symbol.upper(),
        interval=req.interval or "4h",
        generated_at=datetime.now(timezone.utc).isoformat(),
        market_overview=overview,
        decision=decision,
        plan=plan_dict,
        invalidation=invalidation,
        history=history,
        ai_insight=ai_insight,
    )
    return plan.to_dict()


# ---- internal ----------------------------------------------------------------


def _load_position(
    user_id: str, entry: float, stop: float, direction: str, volatility_regime: str
) -> PositionPlan:
    """Load position config from Supabase and compute position size."""
    cfg = get_position_config(user_id)
    if cfg is None or not cfg.get("position_config"):
        return PositionPlan(
            configured=False,
            sizing_note="用户未配置仓位管理，前往仓位页面设置后自动计算",
        )

    pos_cfg = cfg["position_config"]
    total_capital = pos_cfg.get("totalCapitalWu", 0) or 0
    if total_capital <= 0:
        return PositionPlan(configured=False, sizing_note="总资金未设置或为 0")

    appetite = _derive_appetite(pos_cfg)
    return compute_position(entry, stop, direction, total_capital, appetite, volatility_regime)


def _derive_appetite(pos_cfg: dict) -> str:
    """Heuristic: guess risk appetite from config ratios."""
    em = pos_cfg.get("emergencyRatio", 0) or 0
    alt = pos_cfg.get("altcoinMaxRatio", 0) or 0
    if em >= 0.4:
        return "conservative"
    if alt >= 0.2:
        return "aggressive"
    return "balanced"


def _time_stop(interval: str) -> str:
    bars = {"4h": 48, "1d": 20, "1h": 96, "1w": 8}
    n = bars.get(interval, 48)
    return f"{n} 根 {interval} K线未达 TP1 则手动评估"


def _invalidation_trend(direction: str, ema200: float) -> str:
    if direction == LONG:
        return f"收盘价跌破 EMA200 ({ema200:.0f}) → 趋势失效，无条件离场"
    return f"收盘价突破 EMA200 ({ema200:.0f}) → 趋势失效，无条件离场"


def _invalidation_stop(direction: str, stop: float) -> str:
    if direction == LONG:
        return f"4h 收盘跌破 {stop:.2f}（止损位）→ 止损离场"
    return f"4h 收盘突破 {stop:.2f}（止损位）→ 止损离场"


def _invalidation_signal(direction: str) -> str:
    if direction == LONG:
        return "RSI 重新跌破 30 且价格跌破信号K线低点 → 信号无效"
    return "RSI 重新突破 70 且价格突破信号K线高点 → 信号无效"


def _ai_insight(
    overview: Any,
    decision: Decision,
    plan_dict: Optional[dict],
    req: RsiTrendScanRequest,
) -> dict | None:
    """Generate AI insight with per-bar caching."""
    bar_key = getattr(req, "_last_bar_ts", "")
    cache_key = f"{req.symbol}:{req.interval}:{bar_key}"
    if cache_key in _AI_CACHE:
        cached = dict(_AI_CACHE[cache_key])
        cached["cached"] = True
        return cached

    prompt = _build_ai_prompt(overview, decision, plan_dict)
    text = llm_complete(prompt, max_tokens=300)
    if text is None:
        return None

    result = _parse_ai_response(text)
    if result:
        _AI_CACHE[cache_key] = result
    return result


def _build_ai_prompt(overview: Any, decision: Decision, plan: Optional[dict]) -> str:
    parts = [
        "你是一个加密货币交易分析师。根据以下 RSI 趋势策略数据，用中文给出简短解读。",
        f"趋势：{overview.trend}，偏离EMA200：{overview.deviation_pct}%，RSI：{overview.rsi}",
        f"波动率：{overview.volatility_regime}（ATR%={overview.atr_pct}）",
        f"决策：{decision.action}，方向：{decision.direction or '无'}，置信度：{decision.confidence:.0%}",
    ]
    if plan:
        p = plan
        parts.append(f"入场：{p['entry']['price']}，止损：{p['stop']['price']}，TP1：{p['targets'][0]['price']}")
        pos = p.get("position", {})
        if pos.get("configured"):
            parts.append(f"建议仓位：{pos.get('position_size_u')} U")
    parts.append("只输出 JSON：{\"summary\":\"≤120字\", \"risk_note\":\"≤80字\"}")
    return "\n".join(parts)


def _parse_ai_response(text: str) -> dict | None:
    try:
        data = json.loads(text)
        if "summary" in data:
            return {
                "summary": data.get("summary", ""),
                "risk_note": data.get("risk_note", ""),
                "disclaimer": "本分析由 AI 辅助生成，不构成投资建议",
                "cached": False,
            }
        return None
    except (json.JSONDecodeError, ValueError):
        return {
            "summary": text[:240],
            "risk_note": "",
            "disclaimer": "本分析由 AI 辅助生成，不构成投资建议",
            "cached": False,
        }
