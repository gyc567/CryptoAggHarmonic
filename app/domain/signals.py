"""Pure harmonic trading-signal math.

This module is the domain core of the signal engine: every function is pure
(no I/O, no logging, no external state) so it can be unit-tested to 100%
coverage. All prices are plain floats, directions are "long"/"short" strings.

Design rules encoded here (see docs/plans/harmonic-signal-optimization-plan.md):
- Stop loss sits at the pattern invalidation point (X for Gartley/Bat families,
  beyond the PRZ outer edge for Butterfly/Crab families) plus an ATR buffer.
- Take profits are Fibonacci retraces/extensions of the A-D leg: 38.2% / 61.8%
  (retracement) and 127.2% (extension).
- Risk/reward is computed net of fees and slippage.

Three-layer defense notes:
- Layer 3 (Pydantic) — request/response shape lives in :mod:`app.domain.schemas`.
- Layer 2 (this module) — business invariants are enforced via ``icontract``
  decorators on the public pure functions. The contracts assert the
  preconditions the rest of the signal engine relies on (positive ATR,
  finite prices, score range) and the postconditions the caller can trust
  (finite stop, monotonic R/R). They raise ``icontract.ViolationError`` on
  failure — caught and unit-tested in ``tests/test_signals_contract.py``.
- Layer 1 (mypy/pyright) — every public function has full type annotations;
  CI runs both checkers on this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from icontract import ensure, require

from app.config.tuning import TUNING

# --- Backwards-compat aliases (read from TUNING singleton) -----------------
#
# The values formerly defined as module-level constants now live in
# :class:`app.config.tuning.TuningConstants` (see ``app/config/tuning.py``).
# The aliases below preserve the original import paths so existing tests
# (``from app.domain.signals import ATR_STOP_BUFFER``) continue to work.
# Loop-tuning mutates TUNING via :func:`dataclasses.replace`; these aliases
# point at the snapshot taken at import time, which matches the historical
# behaviour of "import this constant at startup and freeze it".

FIB_TP1 = TUNING.fib_tp1
FIB_TP2 = TUNING.fib_tp2
FIB_TP3 = TUNING.fib_tp3
ATR_STOP_BUFFER = dict(TUNING.atr_stop_buffer)
ATR_PRZ_SWEEP = TUNING.atr_prz_sweep
FEE_RATE = TUNING.fee_rate
SLIPPAGE_RATE = TUNING.slippage_rate
TP_CLOSE_PCTS = TUNING.tp_close_pcts
EXTENDED_PATTERNS = frozenset(TUNING.extended_patterns)

# Stop-loss risk levels (三档止损体系) — see TUNING.atr_stop_buffer for buffers.
# Level 1 Conservative: PRZ外 + 1.0*ATR  — 新手,高波动市场
# Level 2 Standard:     D点外 + 0.5*ATR  — 推荐日常使用
# Level 3 Aggressive:   D点内 + 0.25*ATR — 高手,低波动市场
STOP_LOSS_LEVELS = frozenset(TUNING.atr_stop_buffer.keys())

LONG = "long"
SHORT = "short"


# --- Value objects -----------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """A serializable harmonic pattern candidate extracted from pyharmonics."""

    family: str            # XABCD | ABCD | ABC
    name: str              # gartley, bat, butterfly, ...
    bullish: bool
    formed: bool
    points: tuple          # price points (X,A,B,C,D) / (A,B,C,D) / (A,B,C)
    completion_min: float  # PRZ lower bound
    completion_max: float  # PRZ upper bound
    times: tuple = ()      # candle close_times (epoch seconds) of the points (D is last)
    indices: tuple = ()    # bar positions of the points in the source df (D is last)

    @property
    def direction(self) -> str:
        return LONG if self.bullish else SHORT

    @property
    def x_price(self) -> float:
        return float(self.points[0])

    @property
    def a_price(self) -> float:
        # XABCD: A is points[1]; ABCD/ABC families have no X, A is points[0].
        return float(self.points[1]) if self.family == "XABCD" else float(self.points[0])

    @property
    def prz_low(self) -> float:
        return min(self.completion_min, self.completion_max)

    @property
    def prz_high(self) -> float:
        return max(self.completion_min, self.completion_max)


@dataclass(frozen=True)
class SignalTarget:
    label: str
    price: float
    fib_basis: str
    close_pct: int
    move_stop_to: str


@dataclass(frozen=True)
class Signal:
    """A fully specified, executable trade signal."""

    status: str            # approaching | in_prz | confirmed | swept
    grade: str             # A | B | C
    direction: str         # long | short
    pattern_name: str
    family: str
    formed: bool
    entry_zone: tuple      # (low, high)
    entry_reference: float
    stop_loss: float
    stop_basis: str        # human-readable stop placement reason
    stop_level: str        # conservative | standard | aggressive
    invalidation_point: float  # structural point where pattern is invalidated
    targets: tuple         # tuple[SignalTarget, ...]
    net_rr_tp1: float
    net_rr_tp2: float
    confluence_score: int
    confluence: dict = field(default_factory=dict)
    htf_trend: str = "unknown"
    reasoning: str = ""
    sharpe: Optional[float] = None
    regime: str = "normal"
    position_multiplier: Optional[float] = None
    stability_score: Optional[int] = None
    trap_score: Optional[int] = None
    # --- v2 additions (Q7 保留 grade=C 为参考区; Q3/Q4/Q5 联动字段) ---
    tradable: bool = True           # False => grade="C", 仅展示不入场
    macro_advice: Optional[str] = None  # 宏观层建议文案(顺势/逆势/极端位)
    bars_since_c: Optional[int] = None  # 形成中形态:C 点到当前 bar 数
    stale: bool = False             # True => bars_since_c > TTL, 降级不剔除
    breached_stop: bool = False     # True => C 点后路径触达 PRZ(形态已走完)
    past_tp2: bool = False          # True => 现价已穿越 TP2(行情结束)
    width_pct: Optional[float] = None  # PRZ 宽度 / 价格, 用于 grade() 阈值

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "grade": self.grade,
            "direction": self.direction,
            "pattern_name": self.pattern_name,
            "family": self.family,
            "formed": self.formed,
            "entry_zone": [self.entry_zone[0], self.entry_zone[1]],
            "entry_reference": self.entry_reference,
            "stop_loss": self.stop_loss,
            "stop_basis": self.stop_basis,
            "stop_level": self.stop_level,
            "invalidation_point": self.invalidation_point,
            "targets": [
                {
                    "label": t.label,
                    "price": t.price,
                    "fib_basis": t.fib_basis,
                    "close_pct": t.close_pct,
                    "move_stop_to": t.move_stop_to,
                }
                for t in self.targets
            ],
            "net_rr_tp1": self.net_rr_tp1,
            "net_rr_tp2": self.net_rr_tp2,
            "confluence_score": self.confluence_score,
            "confluence": dict(self.confluence),
            "htf_trend": self.htf_trend,
            "reasoning": self.reasoning,
            "sharpe": self.sharpe,
            "regime": self.regime,
            "position_multiplier": self.position_multiplier,
            "stability_score": self.stability_score,
            "trap_score": self.trap_score,
            "tradable": self.tradable,
            "macro_advice": self.macro_advice,
            "bars_since_c": self.bars_since_c,
            "stale": self.stale,
            "breached_stop": self.breached_stop,
            "past_tp2": self.past_tp2,
            "width_pct": self.width_pct,
        }


# --- PRZ state machine --------------------------------------------------------


def prz_state(price: float, prz_low: float, prz_high: float, swept: bool) -> str:
    """Classify the current price relative to the PRZ.

    swept: whether price pierced beyond the PRZ but returned inside it.
    """
    if swept:
        return "swept"
    if prz_low <= price <= prz_high:
        return "in_prz"
    return "approaching"


def is_swept(low: float, high: float, close: float, prz_low: float, prz_high: float) -> bool:
    """Detect a liquidity sweep: wick beyond the PRZ, close back inside it."""
    pierced_below = low < prz_low <= close <= prz_high
    pierced_above = high > prz_high >= close >= prz_low
    return pierced_below or pierced_above


# --- Stop loss ----------------------------------------------------------------


@require(lambda candidate, atr, level="standard": atr > 0,
         "ATR must be positive; compute_stop is undefined for zero volatility")
@require(lambda candidate: candidate.prz_low > 0 and candidate.prz_high > 0,
         "PRZ bounds must be positive; degenerate candidates are filtered upstream")
@require(lambda candidate: all(p > 0 for p in candidate.points),
         "Pattern pivot prices must all be positive")
@ensure(lambda result: result[0] > 0,
        "Returned stop price must be positive")
@ensure(lambda result: result[2] > 0,
        "Returned invalidation point must be positive")
@ensure(lambda result: len(result[1]) > 0,
        "stop_basis must be a non-empty human-readable string")
def compute_stop(candidate: Candidate, atr: float,
                 level: str = "standard") -> tuple[float, str, float]:
    """Stop at the structural invalidation point plus an ATR buffer.

    Args:
        candidate: the harmonic pattern candidate
        atr: current ATR value for the symbol/timeframe
        level: "conservative" | "standard" | "aggressive"

    Returns (stop_price, stop_basis, invalidation_point).
        stop_basis: human-readable reason for stop placement
        invalidation_point: the structural point where the pattern is invalidated
    """
    if level not in STOP_LOSS_LEVELS:
        level = "standard"
    buffer = ATR_STOP_BUFFER[level] * atr
    extended = candidate.name.lower() in EXTENDED_PATTERNS

    if candidate.bullish:
        if level == "conservative":
            # Conservative: PRZ外 + 1.0*ATR（新手/高波动）
            anchor = candidate.prz_low
            basis = f"PRZ外 invalidation - {ATR_STOP_BUFFER[level]:.2f}*ATR"
        elif level == "aggressive":
            # Aggressive: D点内（X附近）+ 0.25*ATR
            anchor = min(candidate.x_price, candidate.prz_low)
            basis = f"X点 invalidation - {ATR_STOP_BUFFER[level]:.2f}*ATR"
        else:
            # Standard: X点/PRZ外 + 0.5*ATR
            anchor = candidate.prz_low if extended else min(candidate.x_price, candidate.prz_low)
            basis = f"X/PRZ invalidation - {ATR_STOP_BUFFER[level]:.2f}*ATR"
        invalidation = round(anchor, 8)
        return round(anchor - buffer, 8), basis, invalidation

    # Bearish
    if level == "conservative":
        anchor = candidate.prz_high
        basis = f"PRZ外 invalidation + {ATR_STOP_BUFFER[level]:.2f}*ATR"
    elif level == "aggressive":
        anchor = max(candidate.x_price, candidate.prz_high)
        basis = f"X点 invalidation + {ATR_STOP_BUFFER[level]:.2f}*ATR"
    else:
        anchor = candidate.prz_high if extended else max(candidate.x_price, candidate.prz_high)
        basis = f"X/PRZ invalidation + {ATR_STOP_BUFFER[level]:.2f}*ATR"
    invalidation = round(anchor, 8)
    return round(anchor + buffer, 8), basis, invalidation


# --- Take profits -------------------------------------------------------------


def compute_targets(candidate: Candidate, entry: float) -> tuple:
    """Fibonacci ladder on the A-D leg: 38.2% / 61.8% retrace, 127.2% extension."""
    a = candidate.a_price
    d = entry  # entry stands in for D (the completion point we trade from)
    span = abs(a - d)
    if candidate.bullish:
        prices = (d + FIB_TP1 * span, d + FIB_TP2 * span, d + FIB_TP3 * span)
    else:
        prices = (d - FIB_TP1 * span, d - FIB_TP2 * span, d - FIB_TP3 * span)
    labels = ("TP1", "TP2", "TP3")
    bases = ("AD 38.2% retrace", "AD 61.8% retrace", "AD 127.2% extension")
    stops = ("breakeven", "tp1", "trail 1*ATR")
    return tuple(
        SignalTarget(
            label=labels[i],
            price=round(prices[i], 8),
            fib_basis=bases[i],
            close_pct=TP_CLOSE_PCTS[i],
            move_stop_to=stops[i],
        )
        for i in range(3)
    )


# --- Net risk/reward ----------------------------------------------------------


@require(lambda entry, stop, target, fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE: entry > 0,
         "Entry price must be positive for risk/reward math")
@require(lambda entry, stop, target, fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE: stop > 0,
         "Stop price must be positive")
@require(lambda entry, stop, target, fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE: target > 0,
         "Target price must be positive")
@require(lambda entry, stop, target, fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE: fee_rate >= 0,
         "fee_rate must be non-negative")
@require(lambda entry, stop, target, fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE: slippage_rate >= 0,
         "slippage_rate must be non-negative")
@ensure(lambda entry, stop, target, result, fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE:
        result is None or result > 0,
        "net_rr returns None for degenerate geometry, otherwise a positive ratio")
def net_rr(entry: float, stop: float, target: float, fee_rate: float = FEE_RATE,
           slippage_rate: float = SLIPPAGE_RATE) -> Optional[float]:
    """Risk/reward of one target, net of round-trip fees and slippage.

    Costs are approximated as (fee + slippage) on both entry and exit notional.
    Returns None when the setup has no positive risk (degenerate geometry).
    """
    risk = abs(entry - stop)
    if risk <= 0 or entry <= 0:
        return None
    cost = 2.0 * (fee_rate + slippage_rate) * entry
    reward = abs(target - entry) - cost
    net_risk = risk + cost
    if reward <= 0 or net_risk <= 0:
        return None
    return round(reward / net_risk, 4)


# --- Grading ------------------------------------------------------------------


@require(lambda score, rr_tp1, rr_tp2, htf_aligned, htf_counter, a_min=75, width_pct=None:
         0 <= score <= 100,
         "score must be a 0-100 confluence value")
@require(lambda score, rr_tp1, rr_tp2, htf_aligned, htf_counter, a_min=75, width_pct=None:
         0 < a_min <= 100,
         "a_min must be in (0, 100]")
@require(lambda score, rr_tp1, rr_tp2, htf_aligned, htf_counter, a_min=75, width_pct=None:
         not (htf_aligned and htf_counter),
         "Aligned and counter cannot both be True")
@ensure(lambda result: result is None or result in ("A", "B", "C(参考)"),
        "grade() returns None or one of A / B / C(参考)")
def grade(score: int, rr_tp1: Optional[float], rr_tp2: Optional[float],
          htf_aligned: bool, htf_counter: bool, a_min: int = 75,
          width_pct: Optional[float] = None) -> Optional[str]:
    """Heuristic A/B/C grade (to be replaced by calibrated quantiles in P3).

    Hard gates: TP1 net R >= 1.0 and TP2 net R >= 1.5, otherwise the signal is
    observation-only (C). Counter-trend signals are capped at C. ``a_min`` is
    the A-grade score threshold (raised in high-quant regimes). ``width_pct``
    is the PRZ width as a fraction of price (Q6 整合); wide PRZ automatically
    degrades to grade C even when the score would otherwise rank higher, so a
    95-score Crab in a 6%-wide PRZ doesn't masquerade as an A.

    Returns:
        "A" / "B" / "C(参考)" — never None for a passing hard-gate score, so
        callers can still emit the signal as a "reference zone" candidate.
    """
    if rr_tp1 is None or rr_tp2 is None:
        return None
    # Width gate (Q6). 4% is the empirical backtest cut-off (see docs).
    if width_pct is not None and width_pct >= 0.04:
        return "C(参考)" if score >= 45 else None
    if htf_counter:
        return "C(参考)" if score >= 45 else None
    if rr_tp1 < 1.0 or rr_tp2 < 1.5:
        return "C(参考)" if score >= 45 else None
    if score >= a_min and rr_tp2 >= 2.0 and htf_aligned:
        return "A"
    if score >= 60:
        return "B"
    if score >= 45:
        return "C(参考)"
    return None


def resolve_analysis_type(signal: Optional[Signal]) -> Optional[str]:
    """Resolve the analysis type actually used, from the engine's output.

    Signal-centric rule (single source of truth): when a signal exists, the
    resolved type mirrors its formed/forming attribute; without a signal the
    answer is None ("no valid signal") -- never a guess based on raw
    candidates, which could contradict what the user actually sees.
    """
    if signal is None:
        return None
    return "formed" if signal.formed else "forming"


def reasoning_from_signal(signal: Signal) -> str:
    """Build the human-readable reasoning text for a signal (Chinese template)."""
    direction = "做多" if signal.direction == LONG else "做空"
    formed = "formed" if signal.formed else "forming"
    lines = [
        f"方向：{direction}（{signal.pattern_name} · {signal.family} · {formed}）",
        f"入场区：{signal.entry_zone[0]:.2f} – {signal.entry_zone[1]:.2f}（参考 {signal.entry_reference:.2f}）",
        f"止损：{signal.stop_loss:.2f}（{signal.stop_basis}，失效点 {signal.invalidation_point:.2f}）",
    ]
    if signal.targets:
        tps = " / ".join(
            f"{t.label} {t.price:.2f}（{t.fib_basis}，平 {t.close_pct}%）"
            for t in signal.targets
        )
        lines.append(f"止盈：{tps}")
    lines.append(f"净盈亏比：TP1 {signal.net_rr_tp1}R / TP2 {signal.net_rr_tp2}R")
    lines.append(f"高周期趋势：{signal.htf_trend}")
    return "\n".join(lines)
