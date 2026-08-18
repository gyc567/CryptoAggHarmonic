"""Harmonic signal → DingTalk Markdown formatter.

Produces three tiers of DingTalk Markdown messages:
  1. Strong signal  (score ≥ 80) — full detail with all confirmation layers
  2. Medium signal (score 60-79) — compact summary
  3. Daily scan summary — aggregate report per user per scan cycle

All formatting uses DingTalk-compatible Markdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from app.infra.dingtalk_client import DingTalkMessage


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

SignalDirection = Literal["bullish", "bearish"]
PatternName    = Literal[
    "Gartley", "Bat", "Butterfly", "Crab", "Shark", "Cypher",
    "DeepCrab", "Anti-Gartley", "5-0", "3-Drive", "AB=CD",
]


@dataclass(frozen=True)
class ScoredSignal:
    """A fully-graded harmonic trading signal."""

    symbol:       str
    pattern:      PatternName
    direction:    SignalDirection
    score:        int
    entry_price:  float
    stop_price:   float
    target_1:    float
    target_2:     float
    atr:         float
    rr_ratio:    float
    # Confirmation breakdown
    trend_ok:     bool
    rsi_div:     bool
    volume_confirm: bool
    volatility_ok: bool
    event_ok:    bool
    # Market regime
    regime:       str   # "bull_market" | "bear_market" | "neutral"
    scan_time_utc: str


# ---------------------------------------------------------------------------
# Emoji / icon helpers
# ---------------------------------------------------------------------------

_DIR_EMOJI   = {"bullish": "🟢",  "bearish": "🔴"}
_DIR_KW      = {"bullish": "看多", "bearish": "看空"}
_GRADE_EMOJI = {"strong": "🚨",  "medium": "⚡", "skip": "🔕"}
_GRADE_KW    = {"strong": "强信号", "medium": "待观察", "skip": "已过滤"}


def _pct(a: float, b: float) -> str:
    """Return b as a percentage change from a, formatted."""
    if b == 0:
        return "N/A"
    chg = ((b - a) / a) * 100
    sign = "+" if chg >= 0 else ""
    return f"{sign}{chg:.1f}%"


def _fmt_price(p: float) -> str:
    """Format a price with appropriate precision."""
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:.2f}"
    return f"{p:.4f}"


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

def format_signal(msg: ScoredSignal) -> DingTalkMessage:
    """Format a single signal into a DingTalk Markdown message."""
    grade = _grade_label(msg.score)
    emoji = _GRADE_EMOJI[grade]
    direction_emoji = _DIR_EMOJI[msg.direction]
    direction_kw    = _DIR_KW[msg.direction]

    title = (
        f"{emoji}【谐波{grade_label_short(grade)}】"
        f"{msg.symbol} 4H · {direction_kw}"
    )

    entry_str = _fmt_price(msg.entry_price)
    stop_str  = _fmt_price(msg.stop_price)
    t1_str    = _fmt_price(msg.target_1)
    t2_str    = _fmt_price(msg.target_2)
    atr_str   = f"{msg.atr:.2f}"

    entry_chg = _pct(msg.entry_price, msg.target_1)
    stop_chg  = _pct(msg.entry_price, msg.stop_price)

    body = f"""## {title}

{direction_emoji} **形态类型**: {msg.pattern} {direction_kw}
📊 **信号评分**: {msg.score}/100
⏰ **评分时间**: {msg.scan_time_utc}

---

### 💰 关键价位

| 价位 | 价格 | 距入场 |
|------|------|--------|
| 入场区间 | {entry_str} | — |
| 目标1   | {t1_str} | {entry_chg} |
| 目标2   | {t2_str} | {_pct(msg.entry_price, msg.target_2)} |
| 止损位   | {stop_str} | {stop_chg} |

💎 **盈亏比**: 1:{msg.rr_ratio:.1f}

---

### ✅ 确认层

| 过滤项 | 状态 |
|--------|------|
| 趋势方向 | {'✅ 同向' if msg.trend_ok else '❌ 逆势'} |
| RSI 分歧 | {'✅ 有分歧' if msg.rsi_div else '❌ 无分歧'} |
| 成交量确认 | {'✅ 放量' if msg.volume_confirm else '❌ 缩量'} |
| 波动率 | {'✅ 正常' if msg.volatility_ok else '⚠️ 异常'} |
| 事件过滤 | {'✅ 无风险事件' if msg.event_ok else '⚠️ 有事件'} |

---

### 📋 交易提示

⏱ **当前市场**: {regime_label(msg.regime)}
📐 **ATR(14)**: {atr_str}
🎯 **仓位建议**: 风险敞口 ≤ 2% 总资金
"""

    if msg.direction == "bullish":
        body += "\n📈 激进者可现价入场，保守者等回调再入。\n"
    else:
        body += "\n📉 激进者可现价入场，保守者等反弹再入。\n"

    body += f"---\n*本信号由 CryptoAggHarmonic 自动生成 · {msg.scan_time_utc}*"
    return DingTalkMessage(title=title, text=body)


def format_medium_signal(msg: ScoredSignal) -> DingTalkMessage:
    """Format a medium-strength signal into a compact DingTalk message."""
    emoji = _GRADE_EMOJI["medium"]
    direction_kw = _DIR_KW[msg.direction]
    entry_str = _fmt_price(msg.entry_price)
    stop_str  = _fmt_price(msg.stop_price)
    t1_str    = _fmt_price(msg.target_1)

    title = f"{emoji}【谐波待观察】{msg.symbol} 4H · {direction_kw}"

    body = f"""## {title}

**形态**: {msg.pattern} {direction_kw}
📊 **评分**: {msg.score}/100

| 入场 | 止损 | 目标1 | 盈亏比 |
|------|------|-------|--------|
| {entry_str} | {stop_str} | {t1_str} | 1:{msg.rr_ratio:.1f} |

**备注**: 等待 RSI 分歧确认后再操作
---
*CryptoAggHarmonic · {msg.scan_time_utc}*"""

    return DingTalkMessage(title=title, text=body)


def format_daily_summary(
    user_id: str,
    scan_time_utc: str,
    symbols_scanned: int,
    strong_signals: list[ScoredSignal],
    medium_signals: list[ScoredSignal],
) -> DingTalkMessage:
    """Format a daily scan summary for a user."""
    total = len(strong_signals) + len(medium_signals)
    title = "📊【4H 谐波扫描日报】" + scan_time_utc[:10]

    body = f"""## {title}

🔍 **扫描范围**: {symbols_scanned} 个自选币种
🚨 **强信号**: {len(strong_signals)} 个
⚡ **待观察**: {len(medium_signals)} 个
🔕 **已过滤**: {symbols_scanned - total} 个

---

"""

    if strong_signals:
        body += "### 🏆 TOP 强信号\n\n"
        for s in sorted(strong_signals, key=lambda x: -x.score)[:5]:
            body += (
                f"- **{s.symbol}** {s.pattern} "
                f"{_DIR_KW[s.direction]} · {s.score}分\n"
            )
        body += "\n"

    if medium_signals:
        body += "### ⚡ 待观察信号\n\n"
        for s in sorted(medium_signals, key=lambda x: -x.score)[:5]:
            body += (
                f"- {s.symbol} {s.pattern} "
                f"{_DIR_KW[s.direction]} · {s.score}分\n"
            )

    if not strong_signals and not medium_signals:
        body += "*今日扫描未发现符合条件的交易信号。*\n"

    body += f"\n---\n*本报告由 CryptoAggHarmonic 自动生成 · {scan_time_utc}*"

    return DingTalkMessage(title=title, text=body)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grade_label(score: int) -> str:
    if score >= 80:
        return "strong"
    if score >= 60:
        return "medium"
    return "skip"


def grade_label_short(grade: str) -> str:
    return _GRADE_KW.get(grade, grade)


def regime_label(regime: str) -> str:
    return {
        "bull_market": "上升趋势 · 顺势做多",
        "bear_market": "下降趋势 · 顺势做空",
        "neutral":     "区间震荡 · 谨慎双向",
    }.get(regime, regime)
