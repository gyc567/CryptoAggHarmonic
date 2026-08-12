"""Experiment verdict helpers (D-FT-19).

Decides KEEP / REVERT / CRASH for a refine operation by comparing metrics
delta from the previous version. Pure function. Mirrors the spirit of
Auto-Quant V2 §"KEEP/REVERT/CRASH Experiments" — the agent decides, but
the helper enforces deterministic policy:

- crash  — drawdown > 2x baseline_drawdown (hard floor; D-FT-19 hard_rule)
- keep   — sharpe improved AND dd within bounds AND win_rate >= 50%
- revert — otherwise

The verdict helper is **advisory**; ``record_experiment`` accepts any
explicit verdict the user passed. This module exists so the API / agent
can ask "given these two metric snapshots, what does the policy say?"
without leaving it implicit.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.loop.tuning_promotion_v3 import DRAWDOWN_MULTIPLIER


VERDICT_KEEP = "keep"
VERDICT_REVERT = "revert"
VERDICT_CRASH = "crash"
ALL_VERDICTS: tuple[str, ...] = (VERDICT_KEEP, VERDICT_REVERT, VERDICT_CRASH)


@dataclass(frozen=True)
class MetricsSnapshot:
    """Subset of metrics used by the verdict policy."""

    sharpe: float
    max_dd: float      # fraction (0.05 = 5%)
    win_rate: float    # fraction
    profit_pct: float  # fraction


@dataclass(frozen=True)
class VerdictResult:
    verdict: str  # 'keep' | 'revert' | 'crash'
    reasoning: str
    is_hard_rule: bool  # True iff verdict was forced (e.g. crash)


def _fmt(v: float) -> str:
    return f"{v:.4f}"


def suggest_verdict(
    prev: MetricsSnapshot,
    curr: MetricsSnapshot,
    *,
    baseline_drawdown: float,
    min_win_rate: float = 0.50,
) -> VerdictResult:
    """Apply the deterministic policy and return a verdict + reasoning.

    Rules (in priority order, first match wins):
    1. **CRASH** if ``curr.max_dd > DRAWDOWN_MULTIPLIER * baseline_drawdown``
       — hard floor to prevent drawdown runaway.
    2. **KEEP** if curr.sharpe >= prev.sharpe AND curr.max_dd <= prev.max_dd
       AND curr.win_rate >= min_win_rate.
    3. **REVERT** otherwise.

    The reasoning string is non-empty and >= 10 characters (D-FT-19 invariant).
    """
    if not isinstance(prev, MetricsSnapshot):
        raise TypeError(f"prev must be MetricsSnapshot, got {type(prev).__name__}")
    if not isinstance(curr, MetricsSnapshot):
        raise TypeError(f"curr must be MetricsSnapshot, got {type(curr).__name__}")

    dd_threshold = DRAWDOWN_MULTIPLIER * baseline_drawdown

    # Rule 1: hard crash
    if curr.max_dd > dd_threshold:
        reasoning = (
            f"CRASH: max_dd {_fmt(curr.max_dd)} > 2x baseline "
            f"{_fmt(baseline_drawdown)} (threshold {_fmt(dd_threshold)}); "
            f"this strategy exceeds drawdown tolerance and must halt."
        )
        return VerdictResult(
            verdict=VERDICT_CRASH,
            reasoning=reasoning,
            is_hard_rule=True,
        )

    # Rule 2: keep (strict improvement on sharpe AND no DD worsening AND win-rate ok)
    improved = curr.sharpe >= prev.sharpe
    no_dd_worse = curr.max_dd <= prev.max_dd
    win_ok = curr.win_rate >= min_win_rate
    if improved and no_dd_worse and win_ok:
        reasoning = (
            f"KEEP: sharpe {prev.sharpe:.4f} -> {curr.sharpe:.4f}, "
            f"max_dd {prev.max_dd:.4f} -> {curr.max_dd:.4f} (no worsening), "
            f"win_rate {curr.win_rate:.4f} >= {min_win_rate:.4f}"
        )
        return VerdictResult(
            verdict=VERDICT_KEEP,
            reasoning=reasoning,
            is_hard_rule=False,
        )

    # Rule 3: revert (catch-all)
    parts: list[str] = []
    if not improved:
        parts.append(f"sharpe regressed {prev.sharpe:.4f} -> {curr.sharpe:.4f}")
    if not no_dd_worse:
        parts.append(f"max_dd worsened {prev.max_dd:.4f} -> {curr.max_dd:.4f}")
    if not win_ok:
        parts.append(f"win_rate {_fmt(curr.win_rate)} below floor {_fmt(min_win_rate)}")
    reasoning = "REVERT: " + "; ".join(parts) if parts else "REVERT: no positive signal"
    return VerdictResult(
        verdict=VERDICT_REVERT,
        reasoning=reasoning,
        is_hard_rule=False,
    )


def _min_reasoning_length() -> int:
    # Lazy-import to avoid module load cycles between tuning_promotion_v3 and this module
    from app.loop.tuning_promotion_v3 import REASONING_MIN_LENGTH
    return REASONING_MIN_LENGTH


def assert_reasoning_satisfies_d_ft_19(reasoning: str) -> None:
    """Defense-in-depth: verify a verdict's reasoning string passes D-FT-19.

    The DB CHECK only enforces NOT NULL; length is enforced at the worker layer
    (REPO + API) — but a user-supplied verdict may bypass the API via UI or
    a CLI test. This helper is exposed so the worker / API layers can call it
    before ``record_experiment``.
    """
    min_len = _min_reasoning_length()
    if not isinstance(reasoning, str) or len(reasoning.strip()) < min_len:
        from app.ft_strategy.supabase_repo import ReasoningEmpty
        raise ReasoningEmpty(
            f"reasoning must be a non-empty string >= {min_len} chars (D-FT-19)"
        )
