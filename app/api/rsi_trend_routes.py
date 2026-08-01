"""API routes for the trend-RSI strategy module.

Methodology: EMA200 defines the trend direction; RSI(14) leaving an
extreme zone defines entry timing. See ``app.domain.rsi_trend``.
"""

import logging
import uuid

from flask import Blueprint, request

from app.api.auth import is_local_dev_mode, require_auth
from app.api.responses import error as _error
from app.api.responses import success as _success
from app.api.validation import parse_request
from app.domain.rsi_trend_schemas import RsiTrendBacktestRequest, RsiTrendScanRequest
from app.infra.supabase_client import (
    consume_ledger_quota,
    log_audit_event,
    release_ledger_quota,
    reserve_user_quota,
)
from app.services import rsi_trend_service
from app.services.rsi_trend_plan_service import build_plan

logger = logging.getLogger(__name__)

rsi_trend_bp = Blueprint("rsi_trend", __name__, url_prefix="/api/rsi-trend")


def _reserve_quota(user_id: str, ref_id: str):
    """Reserve 1 quota unit unless running in local dev mode."""
    if is_local_dev_mode():
        return None
    reserved, _, ledger_id = reserve_user_quota(user_id, ref_id, units=1)
    if not reserved:
        return False
    return ledger_id


@rsi_trend_bp.route("/scan", methods=["GET"])
@require_auth
def scan(user):
    """Scan the latest market state and recent trend-RSI signals."""
    req, err = parse_request(RsiTrendScanRequest, request.args.to_dict())
    if err is not None:
        return err

    ref_id = str(uuid.uuid4())
    ledger_id = _reserve_quota(user["id"], ref_id)
    if ledger_id is False:
        return _error("QUOTA_EXCEEDED", "每日额度已用完", status=429)

    try:
        data = rsi_trend_service.scan(req)
    except Exception:
        if ledger_id:
            release_ledger_quota(ledger_id)
        raise
    if ledger_id:
        consume_ledger_quota(ledger_id)
    log_audit_event(user["id"], "rsi_trend_scan", "strategy", ref_id, {"symbol": req.symbol, "interval": req.interval})
    return _success(data)


@rsi_trend_bp.route("/backtest", methods=["POST"])
@require_auth
def backtest(user):
    """Run a full trend-RSI strategy backtest over a historical window."""
    req, err = parse_request(RsiTrendBacktestRequest, request.get_json(silent=True))
    if err is not None:
        return err

    ref_id = str(uuid.uuid4())
    ledger_id = _reserve_quota(user["id"], ref_id)
    if ledger_id is False:
        return _error("QUOTA_EXCEEDED", "每日额度已用完", status=429)

    try:
        data = rsi_trend_service.backtest(req)
    except Exception:
        if ledger_id:
            release_ledger_quota(ledger_id)
        raise
    if ledger_id:
        consume_ledger_quota(ledger_id)
    log_audit_event(
        user["id"],
        "rsi_trend_backtest",
        "strategy",
        ref_id,
        {"symbol": req.symbol, "interval": req.interval, "lookback_days": req.lookback_days},
    )
    return _success(data)


@rsi_trend_bp.route("/plan", methods=["GET"])
@require_auth
def plan(user):
    """Generate a trading plan with market analysis, decision, position sizing, and AI insight."""
    req, err = parse_request(RsiTrendScanRequest, request.args.to_dict())
    if err is not None:
        return err

    ref_id = str(uuid.uuid4())
    ledger_id = _reserve_quota(user["id"], ref_id)
    if ledger_id is False:
        return _error("QUOTA_EXCEEDED", "每日额度已用完", status=429)

    try:
        data = build_plan(req, user["id"])
    except Exception:
        if ledger_id:
            release_ledger_quota(ledger_id)
        raise
    if ledger_id:
        consume_ledger_quota(ledger_id)
    log_audit_event(
        user["id"], "rsi_trend_plan", "strategy", ref_id,
        {"symbol": req.symbol, "interval": req.interval},
    )
    return _success(data)

