"""D-FT-15 / D-FT-16 — orient + capabilities endpoints.

Auto-Quant V2 pattern: ``aq orient`` returns next actions; ``aq capabilities
--json`` echoes true constants. We mirror that contract so UI / agent can
discover the runtime surface without hardcoding.

Pure functions — no Flask imports — so they can be unit-tested in isolation
and re-used from CLI tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.ft_strategy.supabase_repo import (
    FtStrategyRepo,
    StrategyNotFound,
)
from app.loop.tuning_promotion_v3 import STAGNATION_ROUNDS, module_constants
from app.services.freqtrade.event_log import read_tsv_events
from pathlib import Path

# Default tsv root mirrors app.services.freqtrade.event_log.DEFAULT_TSV_ROOT.
DEFAULT_TSV_ROOT = Path(".scratch/loop_state/ft_strategy")



# ---------------------------------------------------------------------------
# Capabilities (D-FT-16)
# ---------------------------------------------------------------------------


def capabilities_dict() -> dict[str, Any]:
    """Return the endpoint capabilities advertised to UI / agent.

    Sources of truth:
    - module_constants() from app.loop.tuning_promotion_v3
    - the SQL DDL list — exposed for agents that want to introspect schema
    """
    constants = module_constants()
    # Hard limits derived from constants (so capabilities stays in sync).
    return {
        "constants": constants,
        "hard_limits": {
            "MCP_TIMEOUT_SECONDS": constants["MCP_TIMEOUT_SECONDS"],
            "MAX_BACKTEST_PER_GEN": constants["MAX_BACKTEST_PER_GEN"],
            "STAGNATION_ROUNDS": constants["STAGNATION_ROUNDS"],
            "RESEARCH_MD_MIN_LENGTH": constants["RESEARCH_MD_MIN_LENGTH"],
            "CRASH_CLOSURE_WINDOW_DAYS": constants["CRASH_CLOSURE_WINDOW_DAYS"],
        },
        "endpoints": [
            "GET  /api/ft-strategy/capabilities",
            "GET  /api/ft-strategy/orient",
            "GET  /api/ft-strategy/:id/orient",
            "GET  /api/ft-strategies",
            "POST /api/ft-strategies",
            "GET  /api/ft-strategies/:id",
            "DELETE /api/ft-strategies/:id",
            "GET  /api/ft-strategies/:id/jobs",
            "POST /api/ft-strategies/:id/refine",
            "GET  /api/ft-strategies/:id/backtest-report",
            "POST /api/ft-strategies/:id/deploy",
            "GET  /api/ft-strategies/:id/history",
            "POST /api/ft-strategies/:id/preflight",
        ],
        "queue_names": [
            "ft_strategy_create",
            "ft_hyperopt",
            "ft_backtest",
            "ft_analyze",
        ],
    }


# ---------------------------------------------------------------------------
# Orient per-strategy (D-FT-15)
# ---------------------------------------------------------------------------


@dataclass
class NextAction:
    strategy_id: str
    action: str  # 'wait_backtest' | 'refine' | 'apply_deploy_pr' | 'complete_shadow'
    reason: str
    deadline: Optional[str] = None


@dataclass
class HardBlocker:
    label: str
    detail: str


def orient_strategy(
    repo: FtStrategyRepo, strategy_id: str, tsv_root: Optional[Any] = None
) -> dict[str, Any]:
    """Return orient summary for a single strategy.

    Returns a dict that Flask can JSON-serialize directly:
        {
          "strategy_id": ...,
          "current_stage": ...,
          "last_run_id": ... | None,
          "stagnation_count": int,
          "next_action": NextAction | None,
          "hard_blockers": [HardBlocker, ...],
          "recent_events": [dict, ...]  # last 10 events from .tsv
        }
    """
    try:
        strategy = repo.get_strategy(strategy_id)
    except StrategyNotFound:
        return {
            "strategy_id": strategy_id,
            "error": "not_found",
        }

    # Stage derivation
    current_stage = _stage_from_status(strategy.status)

    # Hard blockers
    hard_blockers: list[HardBlocker] = []
    if strategy.status == "rejected":
        hard_blockers.append(HardBlocker(
            label="strategy_rejected",
            detail="Strategy was rejected — likely a crash verdict; create a new strategy instead.",
        ))
    # Open crash gate
    open_crashes = repo.list_open_crashes(strategy_id)
    if open_crashes > 0:
        hard_blockers.append(HardBlocker(
            label="open_crash_unresolved",
            detail=f"{open_crashes} crash verdict(s) without decided_by. Resolve before deploying.",
        ))
    # No final report
    if not repo.has_final_report(strategy_id):
        hard_blockers.append(HardBlocker(
            label="no_final_report",
            detail="Draft a report and publish as final before deploy.",
        ))

    # Last run (latest stage)
    last_run_id = None
    cur = repo.conn.execute(
        "SELECT id, stage, status FROM ft_strategy_runs WHERE strategy_id = ? ORDER BY created_at DESC LIMIT 1",
        (strategy_id,),
    )
    row = cur.fetchone()
    if row is not None:
        last_run_id = row["id"]

    # Stagnation
    stagnation_count = repo.recent_stable_count(strategy_id)

    # Next action: precedence order matters.
    # 1. Strategic lifecycle statuses (rejected / pending_review / deployed / running)
    # 2. Stagnation discipline (analyzed + stagnation >= threshold -> fork)
    # 3. Analyzable + healthy -> refine
    # 4. Otherwise suggest the highest-priority *unblocker* (e.g., draft_report)
    next_action: Optional[NextAction] = None

    # 1. Lifecycle states that are themselves terminal-or-blocked
    if strategy.status == "rejected":
        next_action = NextAction(
            strategy_id=strategy_id,
            action="fork",
            reason="Strategy was rejected; clone into a new strategy to start fresh.",
        )
    elif strategy.status == "pending_review":
        next_action = NextAction(
            strategy_id=strategy_id,
            action="wait_human_merge",
            reason="Deploy PR is awaiting human merge + SIGHUP. Cannot promote without it.",
        )
    elif strategy.status == "deployed":
        next_action = NextAction(
            strategy_id=strategy_id,
            action="monitor_shadow",
            reason="Strategy is live; monitor 7-day shadow period before next variant.",
        )
    elif current_stage in ("hyperopt", "backtest"):
        next_action = NextAction(
            strategy_id=strategy_id,
            action="wait_backtest",
            reason="Background worker is running hyperopt/backtest. Polling /jobs for progress.",
        )
    # 2. Stagnation discipline
    elif (
        strategy.status in ("analyzed", "refining")
        and stagnation_count >= STAGNATION_ROUNDS
    ):
        next_action = NextAction(
            strategy_id=strategy_id,
            action="fork",
            reason=(
                f"Stagnation reached {stagnation_count} >= {STAGNATION_ROUNDS}; "
                "fork or kill (D-FT-22 §1.5)."
            ),
        )
    # Early-stage strategies (draft / code_generated) have no specific
    # next action yet — let the user move them forward manually.
    elif strategy.status in ("draft", "code_generated"):
        next_action = None
    # Open-crash resolution beats iteration (stagnation discipline)
    elif any(b.label == "open_crash_unresolved" for b in hard_blockers):
        next_action = NextAction(
            strategy_id=strategy_id,
            action="resolve_crash",
            reason=(
                "Open crash verdict without decided_by. Either revert the version "
                "or close the crash with decided_by before further iteration."
            ),
        )
    # Analyzable + healthy -> refine
    elif strategy.status in ("analyzed", "refining"):
        next_action = NextAction(
            strategy_id=strategy_id,
            action="refine",
            reason=(
                f"Strategy is analyzable; current version {strategy.current_version}; iterate."
            ),
        )
    # Otherwise suggest highest-priority unblocker
    elif any(b.label == "no_final_report" for b in hard_blockers):
        next_action = NextAction(
            strategy_id=strategy_id,
            action="draft_report",
            reason=(
                "Draft a report (analyze the backtest) and publish as final to enable deploy."
            ),
        )

    # Recent events from .tsv (read-only on success; empty list on failure)
    root = tsv_root if tsv_root is not None else DEFAULT_TSV_ROOT
    try:
        events = read_tsv_events(root, strategy_id)
        recent_events = events[-10:]  # last 10
    except Exception:
        recent_events = []

    return {
        "strategy_id": strategy_id,
        "name": strategy.name,
        "current_stage": current_stage,
        "current_version": strategy.current_version,
        "status": strategy.status,
        "stagnation_count": stagnation_count,
        "last_run_id": last_run_id,
        "next_action": _next_action_to_dict(next_action),
        "hard_blockers": [{"label": b.label, "detail": b.detail} for b in hard_blockers],
        "recent_events": recent_events,
    }


def orient_global(
    repo: FtStrategyRepo,
    strategy_ids: list[str],
    tsv_root: Optional[Any] = None,
) -> dict[str, Any]:
    """Return top-level orient summary across user's strategies."""
    blockers: list[dict[str, Any]] = []
    stagnation_hits: list[dict[str, Any]] = []
    next_actions: list[dict[str, Any]] = []

    for sid in strategy_ids:
        try:
            s = repo.get_strategy(sid)
        except StrategyNotFound:
            continue
        stagnation = repo.recent_stable_count(sid)
        if stagnation >= STAGNATION_ROUNDS:
            stagnation_hits.append({
                "strategy_id": sid,
                "stagnation_count": stagnation,
                "threshold": STAGNATION_ROUNDS,
            })
        orient = orient_strategy(repo, sid, tsv_root=tsv_root)
        hb = orient.get("hard_blockers") or []
        blockers.extend(hb)
        na = orient.get("next_action")
        if na:
            next_actions.append(na)

    return {
        "total_strategies": len(strategy_ids),
        "stagnation_hits": stagnation_hits,
        "hard_blockers": blockers,
        "next_actions": next_actions,
        "loop_health": {
            "loop_id": "13",
            "loop_name": "FT Strategy UI Loop",
            "stagnation_threshold": STAGNATION_ROUNDS,
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stage_from_status(status: str) -> str:
    """Map status to a coarse lifecycle stage label."""
    mapping = {
        "draft": "idea",
        "code_generated": "code",
        "hyperopt_running": "hyperopt",
        "backtest_running": "backtest",
        "analyzed": "analyze",
        "refining": "refine",
        "pending_review": "deploy_pending",
        "deployed": "deployed",
        "rejected": "rejected",
    }
    return mapping.get(status, "unknown")


def _next_action_to_dict(na: Optional[NextAction]) -> Optional[dict[str, Any]]:
    if na is None:
        return None
    return {
        "strategy_id": na.strategy_id,
        "action": na.action,
        "reason": na.reason,
        "deadline": na.deadline,
    }
