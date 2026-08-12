"""FT Strategy UI REST endpoints — Loop #13 (Phase 4).

Wraps ``FtStrategyRepo``, ``orient.py`` and the validators behind a
Flask Blueprint. Routes return the standard ``{success, data}`` /
``{success, error}`` envelope defined in ``app.api.responses``.

Endpoints:

  GET  /api/ft-strategy/capabilities                       (no auth)
  GET  /api/ft-strategy/orient?ids=a,b,c                   auth
  GET  /api/ft-strategy/<id>/orient                        auth
  GET  /api/ft-strategies?user_id=u                       auth
  POST /api/ft-strategies                                 auth
  GET  /api/ft-strategies/<id>                            auth
  DELETE /api/ft-strategies/<id>                          auth
  GET  /api/ft-strategies/<id>/jobs                       auth
  POST /api/ft-strategies/<id>/refine                     auth
  GET  /api/ft-strategies/<id>/backtest-report            auth
  POST /api/ft-strategies/<id>/deploy                     auth
  GET  /api/ft-strategies/<id>/history                    auth
  POST /api/ft-strategies/<id>/preflight                  auth

D-FT-01 require_auth | D-FT-12 source mutex | D-FT-21 clarify-first |
D-FT-22 multi-objective gate | D-FT-23 single source of truth.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from flask import Blueprint, jsonify, request
from app.api.ft_strategy_routes_helpers import _coerce_per_timerange, _jsonify  # noqa: F401

from app.api.auth import require_auth
from app.api.responses import error as _error
from app.api.responses import success as _success
from app.api.validation import parse_request
from app.domain.ft_strategy_schemas import (
    CreateStrategyRequest,
    RefineRequest,
)
from app.ft_strategy.orient import (
    capabilities_dict,
    orient_global,
    orient_strategy,
)
from app.ft_strategy.research_md_validator import validate_research_md
from app.ft_strategy.supabase_repo import (
    FtStrategyError,
    FtStrategyRepo,
    StrategyNotFound,
)
from app.loop.tuning_promotion_v3 import (
    STAGNATION_ROUNDS,
    PromotionCandidate,
    check_promotion_v3,
)

logger = logging.getLogger(__name__)

ft_strategy_bp = Blueprint("ft_strategy", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Repo factory (test override). In production, app.api.routes wires
# set_repo_factory(get_supabase_repo()) via app.infra.supabase_client.
# ---------------------------------------------------------------------------


def _default_repo_factory() -> FtStrategyRepo:
    raise NotImplementedError(
        "Production repo factory is wired in app.api.routes via "
        "set_repo_factory — never call this directly."
    )


_repo_factory = _default_repo_factory


def set_repo_factory(factory) -> None:
    global _repo_factory
    _repo_factory = factory


def _repo() -> FtStrategyRepo:
    return _repo_factory()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strategy_to_dict(s) -> dict[str, Any]:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "name": s.name,
        "description": s.description,
        "market_type": s.market_type,
        "pair": s.pair,
        "interval": s.interval,
        "idea_source": s.idea_source,
        "idea_payload": s.idea_payload,
        "status": s.status,
        "current_version": s.current_version,
        "strategy_file_path": s.strategy_file_path,
        "latest_result": s.latest_result,
        "baseline_comparison": s.baseline_comparison,
        "deployment_pr_url": s.deployment_pr_url,
        "research_md": s.research_md,
        "last_event": s.last_event,
        "stagnation_count": s.stagnation_count,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }


def _row(row) -> Any:
    """Convert sqlite3.Row to namespace attribute (Pydantic-style access)."""
    if hasattr(row, "keys"):
        ns = type("Row", (), {})()
        for k in row.keys():
            setattr(ns, k, row[k])
        return ns
    return row


def _user_id_from_request() -> Optional[str]:
    return (
        request.headers.get("X-User-Id")
        or request.environ.get("ft_user_id")
    )


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validation_failed_response(detail: dict[str, Any]) -> tuple[Any, int]:
    """422 with structured field-level errors (parity with Pydantic-style)."""
    return (
        jsonify({"success": False, "data": detail}),
        422,
    )


# ---------------------------------------------------------------------------
# Capabilities (D-FT-16, no auth — constants only)
# ---------------------------------------------------------------------------


@ft_strategy_bp.get("/ft-strategy/capabilities")
def capabilities():
    return _success(capabilities_dict())


# ---------------------------------------------------------------------------
# Orient (D-FT-15)
# ---------------------------------------------------------------------------


@ft_strategy_bp.get("/ft-strategy/orient")
@require_auth
def orient_root(**kwargs):
    repo = _repo()
    raw_ids = request.args.get("ids", "")
    strategy_ids = [s for s in raw_ids.split(",") if s.strip()]
    return _success(orient_global(repo, strategy_ids))


@ft_strategy_bp.get("/ft-strategy/<strategy_id>/orient")
@require_auth
def orient_one(strategy_id: str, **kwargs):
    repo = _repo()
    return _success(orient_strategy(repo, strategy_id))


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@ft_strategy_bp.get("/ft-strategies")
@require_auth
def list_strategies(**kwargs):
    repo = _repo()
    user_id = request.args.get("user_id") or _user_id_from_request()
    if not user_id:
        return _error("UNAUTHORIZED", "user_id required", status=401)
    cur = repo.conn.execute(
        "SELECT * FROM ft_strategies WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    )
    items = [_strategy_to_dict(_row(r)) for r in cur.fetchall()]
    return _success({"items": items})


@ft_strategy_bp.post("/ft-strategies")
@require_auth
def create_strategy_route(**kwargs):
    """D-FT-21: research_md ≥ 200 字 + 7 sections required."""
    req, err = parse_request(CreateStrategyRequest, request.get_json(silent=True))
    if err is not None:
        return err
    assert req is not None
    assert isinstance(req, CreateStrategyRequest)

    # D-FT-21 clarify-first gate (deeper than Pydantic — runs separately).
    val = validate_research_md(req.research_md)
    if not val.ok:
        return _validation_failed_response(val.to_dict())

    user_id = _user_id_from_request() or "anonymous"
    repo = _repo()
    try:
        s = repo.create_strategy(
            user_id=user_id,
            name=req.name,
            research_md=req.research_md,
            idea_payload=req.idea_payload,
            market_type=req.market_type,
            pair=req.pair,
            interval=req.interval,
            idea_source=req.idea_source,
            description=req.description,
        )
    except FtStrategyError as e:
        return _error("CREATE_FAILED", str(e), status=400)

    # Enqueue worker + record initial event (best-effort).
    _enqueue_strategy_create(s.id, s.current_version)
    try:
        from app.services.freqtrade.event_log import record_event_dual
        record_event_dual(
            repo,
            strategy_id=s.id,
            event="create",
            strategy_name=s.name,
        )
    except Exception:
        pass

    payload = {"success": True, "data": _strategy_to_dict(s)}
    return _jsonify(payload), 201


@ft_strategy_bp.get("/ft-strategies/<strategy_id>")
@require_auth
def get_one(strategy_id: str, **kwargs):
    repo = _repo()
    try:
        s = repo.get_strategy(strategy_id)
    except StrategyNotFound:
        return _error("NOT_FOUND", f"strategy not found: {strategy_id}", status=404)
    return _success(_strategy_to_dict(s))


@ft_strategy_bp.delete("/ft-strategies/<strategy_id>")
@require_auth
def delete_one(strategy_id: str, **kwargs):
    repo = _repo()
    try:
        repo.conn.execute("DELETE FROM ft_strategies WHERE id = ?", (strategy_id,))
        repo.conn.commit()
    except Exception as e:
        return _error("DELETE_FAILED", str(e), status=400)
    return _success({"deleted": strategy_id})


@ft_strategy_bp.get("/ft-strategies/<strategy_id>/jobs")
@require_auth
def jobs_one(strategy_id: str, **kwargs):
    repo = _repo()
    try:
        cur = repo.conn.execute(
            "SELECT * FROM ft_jobs WHERE strategy_id = ? ORDER BY created_at DESC",
            (strategy_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        return _error("QUERY_FAILED", str(e), status=400)
    return _success({"strategy_id": strategy_id, "jobs": rows})


@ft_strategy_bp.post("/ft-strategies/<strategy_id>/refine")
@require_auth
def refine_one(strategy_id: str, **kwargs):
    """D-FT-08 atomic version bump; D-FT-22 stagnation discipline."""
    req, err = parse_request(RefineRequest, request.get_json(silent=True))
    if err is not None:
        return err
    assert req is not None
    assert isinstance(req, RefineRequest)

    repo = _repo()
    try:
        s = repo.get_strategy(strategy_id)
    except StrategyNotFound:
        return _error("NOT_FOUND", f"strategy not found: {strategy_id}", status=404)

    stagnation = repo.recent_stable_count(strategy_id)
    if stagnation >= STAGNATION_ROUNDS and req.intended_event is None:
        return _validation_failed_response({
            "error": "stagnation_discipline",
            "message": (
                f"stagnation reached {stagnation} >= {STAGNATION_ROUNDS}; "
                "intended_event is required (evolve / fork / kill)"
            ),
            "stagnation_count": stagnation,
            "threshold": STAGNATION_ROUNDS,
        })

    s = repo.refine(strategy_id)
    intent = req.intended_event or "evolve"
    try:
        from app.services.freqtrade.event_log import record_event_dual
        record_event_dual(
            repo,
            strategy_id=strategy_id,
            event=intent,
            strategy_name=s.name,
        )
    except Exception:
        pass

    return _success(_strategy_to_dict(s))


@ft_strategy_bp.get("/ft-strategies/<strategy_id>/backtest-report")
@require_auth
def backtest_report(strategy_id: str, **kwargs):
    """D-FT-17: returns BacktestReport shape (§3.5 plan)."""
    repo = _repo()
    try:
        s = repo.get_strategy(strategy_id)
    except StrategyNotFound:
        return _error("NOT_FOUND", f"strategy not found: {strategy_id}", status=404)
    latest = s.latest_result or {}
    return _success({
        "strategy_id": strategy_id,
        "version": s.current_version,
        "aggregate": {
            "sharpe": latest.get("sharpe"),
            "max_dd": latest.get("max_dd"),
            "calmar": latest.get("calmar"),
            "win_rate": latest.get("win_rate"),
            "profit_pct": latest.get("profit_pct"),
            "trades": latest.get("trades"),
            "robust_sharpe_min": latest.get("robust_sharpe_min"),
        },
        "per_pair": latest.get("per_pair", {}),
        "per_timerange": latest.get("per_timerange", {}),
        "baseline_comparison": s.baseline_comparison,
    })


@ft_strategy_bp.post("/ft-strategies/<strategy_id>/deploy")
@require_auth
def deploy_one(strategy_id: str, **kwargs):
    """D-FT-09/10/22: 8-item v3 gate + shadow mode + final report + crash closure.

    Returns 422 with checklist when ANY gate fails; otherwise enqueues
    deploy PR creation. UI never directly modifies app/config/tuning.py.
    """
    repo = _repo()
    try:
        s = repo.get_strategy(strategy_id)
    except StrategyNotFound:
        return _error("NOT_FOUND", f"strategy not found: {strategy_id}", status=404)

    latest = s.latest_result or {}
    open_crashes = repo.list_open_crashes(strategy_id)
    has_final = repo.has_final_report(strategy_id)

    candidate = PromotionCandidate(
        strategy_id=strategy_id,
        version=s.current_version,
        sharpe=latest.get("sharpe", 0.0),
        max_dd=latest.get("max_dd", 0.0),
        calmar=latest.get("calmar", 0.0),
        win_rate=latest.get("win_rate", 0.0),
        profit_pct=latest.get("profit_pct", 0.0),
        trades=latest.get("trades", 0),
        per_timerange=_coerce_per_timerange(latest.get("per_timerange", []) or []),
        has_final_report=has_final,
        open_crash_in_window_days=open_crashes,
    )
    result = check_promotion_v3(candidate)
    if not result.ok:
        return _validation_failed_response({
            "error": "promotion_gate_failed",
            "hard_blockers": list(result.hard_blockers),
            "items": [
                {
                    "label": i.label,
                    "passed": i.passed,
                    "observed": i.observed,
                    "threshold": i.threshold,
                    "note": i.note,
                } for i in result.items
            ],
        })

    # Gate passed; mark pending_review (PR creation wired in Phase 5).
    repo.update_status(strategy_id, "pending_review")
    return _success({
        "strategy_id": strategy_id,
        "status": "pending_review",
        "gate": "passed",
    })


@ft_strategy_bp.get("/ft-strategies/<strategy_id>/history")
@require_auth
def history_one(strategy_id: str, **kwargs):
    """Returns .tsv event log + runs (D-FT-18 mirror)."""
    repo = _repo()
    try:
        repo.get_strategy(strategy_id)
    except StrategyNotFound:
        return _error("NOT_FOUND", f"strategy not found: {strategy_id}", status=404)

    try:
        from app.services.freqtrade.event_log import read_tsv_events
        events = read_tsv_events(
            Path(".scratch/loop_state/ft_strategy"), strategy_id,
        )
    except Exception:
        events = []

    cur = repo.conn.execute(
        "SELECT * FROM ft_strategy_runs WHERE strategy_id = ? ORDER BY created_at",
        (strategy_id,),
    )
    runs = [dict(r) for r in cur.fetchall()]

    return _success({
        "strategy_id": strategy_id,
        "events": events,
        "runs": runs,
    })


@ft_strategy_bp.post("/ft-strategies/<strategy_id>/preflight")
@require_auth
def preflight_one(strategy_id: str, **kwargs):
    """Phase 5 placeholder — concrete 6-item preflight in Phase 5."""
    repo = _repo()
    try:
        repo.get_strategy(strategy_id)
    except StrategyNotFound:
        return _error("NOT_FOUND", f"strategy not found: {strategy_id}", status=404)
    return _success({
        "strategy_id": strategy_id,
        "preflight": "pending_phase_5_implementation",
    })


# ---------------------------------------------------------------------------
# Worker enqueue shim — real RQ wiring lives in Phase 5
# ---------------------------------------------------------------------------


def _enqueue_strategy_create(strategy_id: str, version: int) -> None:
    """Best-effort: record a ft_jobs row so the API can poll /jobs.

    Phase 5 replaces this with ``app.infra.rq.enqueue('ft_strategy_create', ...)``.
    """
    try:
        repo = _repo()
        repo.conn.execute(
            """
            INSERT INTO ft_jobs (job_id, strategy_id, stage, status, started_at)
            VALUES (?, ?, 'code', 'queued', ?)
            """,
            (f"job-{strategy_id}-{version}", strategy_id, _iso_now()),
        )
        repo.conn.commit()
    except Exception:
        pass
