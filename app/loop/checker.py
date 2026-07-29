"""Checker — second-opinion review of each candidate.

Plan §4 says the checker is "the same model with a different prompt" — it
reviews the candidate's metrics, the diff vs the parent, and the regime
distribution, then issues a verdict ("promising" / "suspicious" /
"rejected") with reasoning.

This module implements the *non-LLM* version of the checker. The
heuristics below mirror the prompt an LLM checker would be expected to
follow; we expose them as plain Python so they're testable in CI. When
the operator enables an LLM checker (out of scope for M4) it should
implement the same :class:`Checker` interface so callers don't change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.loop.worker import CandidateResult


# --- Public types ------------------------------------------------------------


@dataclass
class CheckerVerdict:
    """The checker's opinion on one candidate."""

    candidate_id: str
    decision: str  # "promising" | "suspicious" | "rejected"
    confidence: float  # 0..1, how sure we are
    reasons: list[str]
    flags: list[str]  # structured signals — regime imbalance, etc.


# --- Heuristic rules ---------------------------------------------------------


def _flag_regime_imbalance(metrics: dict) -> Optional[str]:
    """Return a flag string if trades are heavily skewed to one regime."""
    regimes = metrics.get("by_regime", {})
    counts = {k: v.get("n", 0) for k, v in regimes.items() if v.get("n", 0)}
    total = sum(counts.values())
    if total < 10:
        return None
    dominant = max(counts.values()) / total
    if dominant > 0.85:
        return f"regime_imbalance:{max(counts, key=counts.get)}={dominant:.0%}"
    return None


def _flag_low_sample(metrics: dict) -> Optional[str]:
    tc = metrics.get("trades_count", 0)
    if tc < 30:
        return f"low_sample:{tc}_trades"
    return None


def _flag_bear_regime_sharpe(metrics: dict) -> Optional[str]:
    regimes = metrics.get("by_regime", {})
    bear = regimes.get("bear") or regimes.get("range", {})
    if bear.get("n", 0) < 3:
        return None
    s = bear.get("sharpe")
    if s is None or s < -1.0:
        return f"bear_sharpe_extreme:{s:+.2f}" if s is not None else "bear_sharpe_missing"
    return None


# --- Main entry --------------------------------------------------------------


def check_candidate(
    result: CandidateResult,
    *,
    parent_metrics: Optional[dict] = None,
) -> CheckerVerdict:
    """Run the heuristic checker on ``result``.

    ``parent_metrics`` is the parent's metrics blob — used to spot
    suspicious gains (e.g. fitness doubled but trade count halved ⇒
    probably overfit). Pass ``None`` if the parent was a fresh restart.
    """
    flags: list[str] = []
    reasons: list[str] = []
    m = result.metrics or {}

    # Low sample size — auto-suspicious.
    low = _flag_low_sample(m)
    if low:
        flags.append(low)
        reasons.append(f"sample size {m.get('trades_count', 0)} < 30")

    # Regime imbalance — auto-suspicious.
    imb = _flag_regime_imbalance(m)
    if imb:
        flags.append(imb)
        reasons.append(f"trades skewed to one regime ({imb})")

    # Bear regime extreme — auto-suspicious (likely overfit to one regime).
    bear = _flag_bear_regime_sharpe(m)
    if bear:
        flags.append(bear)
        reasons.append("bear-regime sharpe suggests overfit to trending market")

    # Parent comparison — if fitness doubled but trade count dropped
    # sharply, flag as suspicious.
    if parent_metrics is not None and m.get("fitness") and parent_metrics.get("fitness"):
        f_new = m["fitness"]
        f_old = parent_metrics["fitness"]
        tc_new = m.get("trades_count", 0)
        tc_old = parent_metrics.get("trades_count", 0)
        if f_new > 2 * f_old and tc_new < max(15, tc_old * 0.5):
            flags.append("fitness_gain_trade_drop")
            reasons.append(
                f"fitness {f_old:.2f}→{f_new:.2f} but trades {tc_old}→{tc_new} "
                f"(likely overfit / cherry-picked)"
            )

    # Decision roll-up.
    if result.decision != "accepted":
        # Worker already rejected; checker's verdict is informational.
        decision = "rejected"
        confidence = 0.9
    elif flags:
        decision = "suspicious"
        # More flags ⇒ lower confidence in the candidate.
        confidence = max(0.0, 0.7 - 0.15 * len(flags))
    else:
        decision = "promising"
        confidence = 0.7

    return CheckerVerdict(
        candidate_id=result.candidate_id,
        decision=decision,
        confidence=confidence,
        reasons=reasons or ["no red flags detected"],
        flags=flags,
    )