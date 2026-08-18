"""Signal grader: computes a 0-100 quality score for a harmonic candidate.

Scoring breakdown:
  * Pattern completeness (0-40 pts)
  * Confirmation layers     (0-30 pts)
  * Market context         (0-30 pts)
  * ─────────────────────
  * Total                  (0-100 pts)

Thresholds:
  * ≥ 80 → strong signal   (full notification)
  * 60-79 → medium signal (compact notification)
  * < 60 → skip           (log only)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.market_regime import MarketRegimeResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_SCORE_STRONG  = 80
MIN_SCORE_MEDIUM  = 60
MIN_RR_RATIO      = 1.5   # must have at least 1.5:1 to qualify

# Pattern completeness (max 40 pts)
PATTERN_SCORE_MAX = 40

# Confirmation layers (max 30 pts)
CONF_RSI_DIVERGENCE  = 10
CONF_VOLUME          = 10
CONF_TRENDLINE       = 10

# Market context (max 30 pts)
CONTEXT_TREND        = 15
CONTEXT_ATR          = 8
CONTEXT_EVENT        = 7


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GradeResult:
    total:          int
    pattern_score:  int
    confirm_score:  int
    context_score:  int
    grade:          str          # "strong" | "medium" | "skip"
    reasons:        tuple[str, ...]  # reasons for deductions
    passes_rr:      bool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def grade_signal(
    *,
    pattern_score:  float,   # 0-1 normalized completeness
    rsi_divergence: bool,
    volume_confirm: bool,
    regime_result,            # MarketRegimeResult
    direction: str,           # "bullish" | "bearish"
    rr_ratio:   float,
    atr_ratio:  float,
    event_clear: bool,
) -> GradeResult:
    """Compute the overall signal quality score.

    Args:
        pattern_score:   0.0-1.0 (how complete the harmonic is)
        rsi_divergence:  True if RSI divergence detected
        volume_confirm:  True if volume confirms the reversal
        regime_result:   MarketRegimeResult from market_regime module
        direction:       "bullish" or "bearish"
        rr_ratio:        reward-to-risk ratio
        atr_ratio:       current ATR14 / ATR20 ratio
        event_clear:     True if no high-impact events nearby
    """
    reasons: list[str] = []

    # ── 1. Pattern completeness (0-40) ───────────────────────────────
    pat = int(pattern_score * PATTERN_SCORE_MAX)
    if pat < PATTERN_SCORE_MAX * 0.7:
        reasons.append(f"pattern_incomplete({pat}/{PATTERN_SCORE_MAX})")

    # ── 2. Confirmation layers (0-30) ────────────────────────────────
    conf = 0
    if rsi_divergence:
        conf += CONF_RSI_DIVERGENCE
    else:
        reasons.append("no_rsi_divergence")

    if volume_confirm:
        conf += CONF_VOLUME
    else:
        reasons.append("no_volume_confirm")

    # ── 3. Market context (0-30) ─────────────────────────────────────
    ctx = 0
    regime = regime_result.regime if regime_result else "neutral"

    if regime in ("bull_market", "bear_market"):
        if _direction_matches_regime(direction, regime):
            ctx += CONTEXT_TREND
        else:
            reasons.append(f"direction_regime_conflict({direction}/{regime})")
            ctx += CONTEXT_TREND // 3  # partial credit

    # ATR health
    if 0.5 <= atr_ratio <= 2.0:
        ctx += CONTEXT_ATR
    else:
        reasons.append(f"atr_unhealthy({atr_ratio:.1f}x)")

    # Event check
    if event_clear:
        ctx += CONTEXT_EVENT
    else:
        reasons.append("event_blackout")

    # ── 4. RR ratio gate ────────────────────────────────────────────
    passes_rr = rr_ratio >= MIN_RR_RATIO

    total = min(pat + conf + ctx, 100)
    if not passes_rr:
        total = max(total - 20, 0)
        reasons.append(f"rr_too_low({rr_ratio:.1f}<{MIN_RR_RATIO})")

    # ── 5. Grade label ────────────────────────────────────────────────
    if total >= MIN_SCORE_STRONG:
        grade = "strong"
    elif total >= MIN_SCORE_MEDIUM:
        grade = "medium"
    else:
        grade = "skip"

    return GradeResult(
        total=total,
        pattern_score=pat,
        confirm_score=conf,
        context_score=ctx,
        grade=grade,
        reasons=tuple(reasons),
        passes_rr=passes_rr,
    )


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _direction_matches_regime(direction: str, regime: str) -> bool:
    return (direction == "bullish" and regime == "bull_market") or \
           (direction == "bearish" and regime == "bear_market")
