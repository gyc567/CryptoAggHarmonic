"""v3 multi-objective promotion gate — pure function (D-FT-23).

ADR-0012 D4: deploy-prerequisite 8-item multi-objective gate. Lives alongside
``app/loop/tuning_promotion.py`` (which owns v2 ``promotion_checklist()`` and
existing path-level/tool-level gates). v3 adds a single pure function
``check_promotion_v3()`` so UI, agent, CLI share one source of truth.

Design constraints (D-FT-23):
- Pure function: no I/O, no exceptions raised for legitimate-false returns.
- Returns a structured ``PromotionResult`` (dataclass), not strings, so the
  same object can be serialized for UI / durable-facts / agent logs.
- All eight items in §6.5 of the plan map to one boolean in the result, with
  the underlying metric retained for transparency.
- Promotion to live TUNING is forbidden here — that path-level gate is owned
  by ``promotion_allowed_for_files()`` in ``tuning_promotion.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Constants — sourced from existing ADR where applicable (D-FT-23: capabilities
# endpoint must echo these exact literals; do not wrap in env vars).
# ---------------------------------------------------------------------------

# ADR-0010 D5 / ADR-0012 D4 item 3
DEFAULT_DRAWDOWN_BASELINE: float = 0.156  # freqtrade-baseline-01 placeholder
DRAWDOWN_MULTIPLIER: float = 2.0

# ADR-0012 D4 item 4 — Auto-Quant V1 v0.4.1 profit_floor (防止 vol_target 退化)
DEFAULT_PROFIT_FLOOR: float = 0.05  # +5% absolute

# ADR-0012 D4 item 5 — 与现有 `[freqtrade-baseline-01]` accepted >= 30 floor 对齐
DEFAULT_MIN_POSITION_SIZE: int = 30  # trades count floor

# ADR-0012 D4 item 1 — robust_sharpe_min floor (worst-case across regimes)
DEFAULT_ROBUST_SHARPE_MIN: float = 0.0

# ADR-0012 D4 item 2 — robust_calmar_min floor
DEFAULT_ROBUST_CALMAR_MIN: float = 1.0

# Stagnation (D-FT decision §1.5) — Auto-Quant V1 "program.md" §Stagnation rule
STAGNATION_ROUNDS: int = 3

# Crash-closure window (ADR-0012 D4 item 8)
CRASH_CLOSURE_WINDOW_DAYS: int = 7

# Reasoning minimum length (ADR-0012 D7 / D-FT-19)
REASONING_MIN_LENGTH: int = 10

# Research.md minimum length (D-FT-21)
RESEARCH_MD_MIN_LENGTH: int = 200


@dataclass(frozen=True)
class PerTimerangeResult:
    """Per regime metrics — input to robust_sharpe / robust_calmar items."""

    regime: str  # 'bull_2021' | 'winter_2022' | 'recovery_2023' | 'full_5y' | custom
    sharpe: float
    max_dd: float
    calmar: float


@dataclass(frozen=True)
class PromotionCandidate:
    """The strategy candidate + the experiments / reports referencing it."""

    strategy_id: str
    version: int

    # Aggregate metrics from latest backtest run
    sharpe: float
    max_dd: float  # fraction (0.078 = 7.8%)
    calmar: float
    win_rate: float  # fraction
    profit_pct: float  # fraction
    trades: int

    # Per-regime breakouts
    per_timerange: tuple[PerTimerangeResult, ...] = ()

    # Cross-reference state
    has_final_report: bool = False
    open_crash_in_window_days: int = 0  # count of crash verdicts without decided_by in last 7d


@dataclass(frozen=True)
class PromotionContext:
    """External state required by the gate."""

    baseline_drawdown: float = DEFAULT_DRAWDOWN_BASELINE
    profit_floor: float = DEFAULT_PROFIT_FLOOR
    min_position_size: int = DEFAULT_MIN_POSITION_SIZE
    robust_sharpe_min: float = DEFAULT_ROBUST_SHARPE_MIN
    robust_calmar_min: float = DEFAULT_ROBUST_CALMAR_MIN

    # Pareto-dominance: candidate_shapes is a list of (sharpe, calmar, max_dd, win_rate)
    # tuples representing this user's prior KEEP candidate shape points.
    prior_keep_shapes: tuple[tuple[float, float, float, float], ...] = ()


@dataclass(frozen=True)
class PromotionCheckItem:
    label: str  # human-readable label, e.g. "robust_sharpe_min"
    passed: bool
    observed: Optional[float] = None
    threshold: Optional[float] = None
    note: str = ""


@dataclass(frozen=True)
class PromotionResult:
    ok: bool
    items: tuple[PromotionCheckItem, ...]
    hard_blockers: tuple[str, ...] = ()
    soft_warnings: tuple[str, ...] = ()

    def failing_items(self) -> tuple[PromotionCheckItem, ...]:
        return tuple(i for i in self.items if not i.passed)


def _pareto_dominated(
    candidate: tuple[float, float, float, float],
    priors: tuple[tuple[float, float, float, float], ...],
) -> bool:
    """True if any prior strictly dominates candidate in all 4 dimensions.

    Dimensions: (sharpe, calmar, -max_dd, win_rate).
    A prior dominates if its tuple is >= candidate on every coord (where
    larger-is-better applies: sharpe, calmar, win_rate) and strictly
    better on at least one. We flip max_dd sign so larger is better.
    """
    cs, cc, cdd_neg, cwr = candidate
    for ps, pc, pdd_neg, pwr in priors:
        # All coordinates are >= candidate (so prior is at least as good)
        # and at least one is strictly > (so prior is not equal).
        ge_all = (ps >= cs) and (pc >= cc) and (pdd_neg >= cdd_neg) and (pwr >= cwr)
        gt_one = (ps > cs) or (pc > cc) or (pdd_neg > cdd_neg) or (pwr > cwr)
        if ge_all and gt_one:
            return True
    return False


def check_promotion_v3(
    candidate: PromotionCandidate,
    ctx: Optional[PromotionContext] = None,
) -> PromotionResult:
    """Evaluate the 8-item v3 multi-objective gate. Pure function. No I/O.

    1. ``robust_sharpe_min`` — min(per_timerange.sharpe) >= ctx.robust_sharpe_min
    2. ``robust_calmar_min`` — min(per_timerange.calmar) >= ctx.robust_calmar_min
    3. ``max_drawdown`` — candidate.max_dd <= DRAWDOWN_MULTIPLIER × ctx.baseline_drawdown
    4. ``profit_floor`` — candidate.profit_pct >= ctx.profit_floor
    5. ``min_position_size`` — candidate.trades >= ctx.min_position_size
    6. ``not pareto_dominated_by`` — candidate not strictly dominated by any prior KEEP
    7. ``report_referenced`` — candidate.has_final_report is True
    8. ``no_open_crash_in_window`` — candidate.open_crash_in_window_days == 0

    Defensive: does not raise for legitimate-false returns; type-check failures
    yield a structured PromotionResult.ok=False result (D-FT-23).
    """
    if not isinstance(candidate, PromotionCandidate):
        return PromotionResult(
            ok=False,
            items=(PromotionCheckItem(
                label="type_check",
                passed=False,
                note=f"candidate must be PromotionCandidate, got {type(candidate).__name__}",
            ),),
            hard_blockers=("type_check",),
        )
    if ctx is None:
        ctx = PromotionContext()
    if not isinstance(ctx, PromotionContext):
        return PromotionResult(
            ok=False,
            items=(PromotionCheckItem(
                label="type_check",
                passed=False,
                note=f"context must be PromotionContext, got {type(ctx).__name__}",
            ),),
            hard_blockers=("type_check",),
        )

    items: list[PromotionCheckItem] = []

    # 1. robust_sharpe_min
    if candidate.per_timerange:
        sharpes = [r.sharpe for r in candidate.per_timerange]
        min_sharpe = min(sharpes)
        items.append(PromotionCheckItem(
            label="robust_sharpe_min",
            passed=min_sharpe >= ctx.robust_sharpe_min,
            observed=round(min_sharpe, 4),
            threshold=ctx.robust_sharpe_min,
            note=f"min(per_timerange.sharpe) across {len(sharpes)} regime(s)",
        ))
    else:
        items.append(PromotionCheckItem(
            label="robust_sharpe_min",
            passed=False,
            observed=None,
            threshold=ctx.robust_sharpe_min,
            note="no per_timerange rows; cannot evaluate",
        ))

    # 2. robust_calmar_min
    if candidate.per_timerange:
        calmars = [r.calmar for r in candidate.per_timerange]
        min_calmar = min(calmars)
        items.append(PromotionCheckItem(
            label="robust_calmar_min",
            passed=min_calmar >= ctx.robust_calmar_min,
            observed=round(min_calmar, 4),
            threshold=ctx.robust_calmar_min,
            note=f"min(per_timerange.calmar) across {len(calmars)} regime(s)",
        ))
    else:
        items.append(PromotionCheckItem(
            label="robust_calmar_min",
            passed=False,
            observed=None,
            threshold=ctx.robust_calmar_min,
            note="no per_timerange rows; cannot evaluate",
        ))

    # 3. max_drawdown <= 2x baseline
    drawdown_threshold = DRAWDOWN_MULTIPLIER * ctx.baseline_drawdown
    items.append(PromotionCheckItem(
        label="max_drawdown",
        passed=candidate.max_dd <= drawdown_threshold,
        observed=round(candidate.max_dd, 4),
        threshold=round(drawdown_threshold, 4),
        note=f"<= {DRAWDOWN_MULTIPLIER} × baseline={ctx.baseline_drawdown:.4f}",
    ))

    # 4. profit_floor
    items.append(PromotionCheckItem(
        label="profit_floor",
        passed=candidate.profit_pct >= ctx.profit_floor,
        observed=round(candidate.profit_pct, 4),
        threshold=ctx.profit_floor,
        note="Auto-Quant V1 v0.4.1 (vol-target degeneracy guard)",
    ))

    # 5. min_position_size (trades >= floor)
    items.append(PromotionCheckItem(
        label="min_position_size",
        passed=candidate.trades >= ctx.min_position_size,
        observed=float(candidate.trades),
        threshold=float(ctx.min_position_size),
        note=f"trades >= {ctx.min_position_size}",
    ))

    # 6. not pareto dominated by prior keeps
    candidate_shape = (candidate.sharpe, candidate.calmar, -candidate.max_dd, candidate.win_rate)
    dominated = _pareto_dominated(candidate_shape, ctx.prior_keep_shapes)
    items.append(PromotionCheckItem(
        label="not_pareto_dominated",
        passed=not dominated,
        observed=None,
        threshold=None,
        note="checked against {n} prior KEEP shape(s)".format(n=len(ctx.prior_keep_shapes)),
    ))

    # 7. report_referenced
    items.append(PromotionCheckItem(
        label="report_referenced",
        passed=candidate.has_final_report,
        observed=None,
        threshold=None,
        note="requires ft_strategy_reports.authoring_state='final'",
    ))

    # 8. no_open_crash_in_window (crash verdicts without decided_by in last 7d)
    items.append(PromotionCheckItem(
        label="no_open_crash_in_window",
        passed=candidate.open_crash_in_window_days == 0,
        observed=float(candidate.open_crash_in_window_days),
        threshold=0.0,
        note=f"closed within last {CRASH_CLOSURE_WINDOW_DAYS} days",
    ))

    failing = [i for i in items if not i.passed]
    blockers = tuple(i.label for i in failing)
    return PromotionResult(
        ok=not failing,
        items=tuple(items),
        hard_blockers=blockers,
    )


def assert_crash_closure_window(days: int) -> int:
    """Crash closure window sanity check.

    Defensive helper for the agent / deploy endpoint: refuses windows that
    exceed 90 days, since longer windows mask indefinite open crashes.
    """
    if not isinstance(days, int):
        raise TypeError(f"days must be int, got {type(days).__name__}")
    if days < 0:
        raise ValueError(f"days must be >= 0, got {days}")
    if days > 90:
        raise ValueError(f"days must be <= 90 (per ADR-0012 D4 window); got {days}")
    return days


def module_constants() -> dict[str, int | float]:
    """Return the constants exposed via ``GET /api/ft-strategy/capabilities``.

    Source of truth for D-FT-16: capabilities endpoint must echo these literal
    values; do not double-wrap in env vars.
    """
    # Import mcp_client constants here (deferred to avoid module load cycle).
    from app.services.freqtrade.mcp_client import MCP_TIMEOUT_SECONDS, MAX_BACKTEST_PER_GEN

    return {
        "MCP_TIMEOUT_SECONDS": MCP_TIMEOUT_SECONDS,
        "MAX_BACKTEST_PER_GEN": MAX_BACKTEST_PER_GEN,
        "STAGNATION_ROUNDS": STAGNATION_ROUNDS,
        "RESEARCH_MD_MIN_LENGTH": RESEARCH_MD_MIN_LENGTH,
        "REASONING_MIN_LENGTH": REASONING_MIN_LENGTH,
        "CRASH_CLOSURE_WINDOW_DAYS": CRASH_CLOSURE_WINDOW_DAYS,
        "DEFAULT_PROFIT_FLOOR": DEFAULT_PROFIT_FLOOR,
        "DEFAULT_MIN_POSITION_SIZE": DEFAULT_MIN_POSITION_SIZE,
        "DEFAULT_ROBUST_SHARPE_MIN": DEFAULT_ROBUST_SHARPE_MIN,
        "DEFAULT_ROBUST_CALMAR_MIN": DEFAULT_ROBUST_CALMAR_MIN,
        "DEFAULT_DRAWDOWN_BASELINE": DEFAULT_DRAWDOWN_BASELINE,
        "DRAWDOWN_MULTIPLIER": DRAWDOWN_MULTIPLIER,
    }
