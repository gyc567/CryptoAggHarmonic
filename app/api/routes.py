"""API blueprint for the SaaS analysis endpoints.

Routes:
- GET  /api/health         — health check
- GET  /api/markets        — supported markets/intervals
- POST /api/analyze        — structured analysis
- GET  /api/history        — analysis history
- GET  /api/analysis/<id>  — analysis detail
- POST /query              — legacy OpenAI query endpoint
- GET  /                   — chat UI
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, render_template, request

from app.api.auth import check_quota, is_local_dev_mode, require_auth
from app.api.errors import AppError
from app.api.responses import error as _error
from app.api.validation import parse_request
from app.domain.enums import AnalysisType, ErrorCode, Interval, Market
from app.domain.schemas import (
    AnalyzeRequest,
    ErrorResponse,
    HealthResponse,
    MarketsResponse,
    SuccessResponse,
)
from app.factory import get_orchestrator
from app.infra.health_check import run_health_checks
from app.infra.supabase_client import (
    consume_ledger_quota,
    create_analysis_record,
    delete_analysis_record,
    get_analysis_by_idem_key,
    log_audit_event,
    release_ledger_quota,
    update_analysis_record,
)

if TYPE_CHECKING:
    from flask import Flask

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)


# ---- Health & Info ----


@api_bp.route("/api/health", methods=["GET"])
def health_check():
    """Health check endpoint with dependency status."""
    import time

    result = run_health_checks()
    response = HealthResponse(
        status=result["status"],
        timestamp=str(int(time.time())),
        version="0.2.0",
    ).model_dump()
    response["checks"] = result["checks"]
    status_code = 503 if result["status"] == "error" else 200
    return jsonify(response), status_code


@api_bp.route("/api/markets", methods=["GET"])
def get_markets():
    """Return supported markets, intervals, and analysis types."""
    return (
        jsonify(
            MarketsResponse(
                markets=[m.value for m in Market],
                intervals=[i.value for i in Interval],
                analysis_types=[a.value for a in AnalysisType],
            ).model_dump()
        ),
        200,
    )


# ---- Analysis ----


@api_bp.route("/api/analyze", methods=["POST"])
@require_auth
def analyze(user):
    """Structured analysis endpoint with auth and quota."""
    user_id = user.get("id")

    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None

    # Validate request.
    req, err = parse_request(AnalyzeRequest, data)
    if err is not None:
        return err

    # Idempotency short-circuit.
    if req.idempotency_key:
        prior = get_analysis_by_idem_key(user_id, req.idempotency_key)
        if isinstance(prior, dict) and prior.get("status") == "completed" and prior.get("technical_result"):
            replayed_id = prior.get("id") or str(uuid.uuid4())
            logging.info("Replaying analysis by idempotency_key=%s", req.idempotency_key)
            return (
                jsonify(
                    SuccessResponse(
                        data={
                            "analysis_id": replayed_id,
                            "status": prior.get("status", "completed"),
                            "market": prior.get("market"),
                            "symbol": prior.get("symbol"),
                            "interval": prior.get("interval"),
                            "analysis_type": prior.get("analysis_type"),
                            "technical_result": prior.get("technical_result"),
                            "interpretation": prior.get("interpretation"),
                            "chart": {},
                            "timing": {
                                "duration_ms": prior.get("duration_ms"),
                                "started_at": prior.get("started_at"),
                                "completed_at": prior.get("completed_at"),
                            },
                            "idempotent_replay": True,
                        }
                    ).model_dump()
                ),
                200,
            )

    # Create analysis record FIRST so the quota reservation below can
    # reference it (usage_ledger.analysis_id has an FK to analyses).
    analysis_id = str(uuid.uuid4())
    record_payload = {
        "input_mode": "form",
        "market": req.market.value,
        "symbol": req.symbol,
        "interval": req.interval.value,
        "analysis_type": req.analysis_type.value,
        "parameters": req.model_dump(),
        "status": "created",
    }
    if req.idempotency_key:
        record_payload["idempotency_key"] = req.idempotency_key

    record_id = create_analysis_record(
        user_id,
        record_payload,
        analysis_id=analysis_id,
    )
    if is_local_dev_mode() and not record_id:
        logging.warning("Local dev: analysis record creation skipped/failed")

    # Reserve quota (after record creation so usage_ledger FK resolves).
    if is_local_dev_mode():
        reserved, remaining, ledger_id = True, 100, None
    else:
        reserved, remaining, ledger_id = check_quota(user_id, analysis_id, units=1)
    if not reserved:
        # Remove the placeholder record so we don't leave orphaned "created" rows.
        if record_id and not is_local_dev_mode():
            try:
                delete_analysis_record(record_id)
            except Exception:
                logging.exception("Failed to clean up analysis record after quota rejection")
        return (
            jsonify(
                ErrorResponse(
                    error={
                        "code": "QUOTA_EXCEEDED",
                        "message": f"Daily quota exceeded. Remaining: {remaining}",
                        "retryable": False,
                        "request_id": "",
                    }
                ).model_dump()
            ),
            429,
        )

    # Run analysis.
    try:
        orchestrator = get_orchestrator()
        result = orchestrator.analyze(req, user_id=user_id, analysis_id=analysis_id)

        # Consume quota. Token counts are not tracked yet (TimingInfo has no
        # token fields), so pass None — consume_ledger_quota accepts Optional.
        if ledger_id:
            consume_ledger_quota(ledger_id, input_tokens=None, output_tokens=None)

        # Persist completion status.
        result_summary = None
        signal = result.technical_result.signal if result.technical_result else None
        if signal:
            result_summary = {
                "direction": signal.direction,
                "pattern": signal.pattern_name,
                "grade": signal.grade,
                "formed": signal.formed,
            }
        if record_id:
            update_analysis_record(
                record_id,
                {
                    "status": "completed",
                    # Persist the engine's resolved type for auto requests
                    # (the placeholder row was created with a legal CHECK
                    # value; the real answer arrives after the run).
                    "analysis_type": result.technical_result.resolved_type
                    if result.technical_result and result.technical_result.resolved_type
                    else None,
                    "result_summary": result_summary,
                },
            )

        # Log audit.
        log_audit_event(
            actor_id=user_id,
            action="analysis_completed",
            target_type="analysis",
            target_id=analysis_id,
            details={"symbol": req.symbol, "market": req.market.value},
        )

        return jsonify(SuccessResponse(data=result.model_dump()).model_dump()), 200

    except AppError as e:
        if ledger_id:
            release_ledger_quota(ledger_id)
        if record_id:
            update_analysis_record(record_id, {"status": "failed_upstream", "error_message": str(e)})
        raise
    except Exception as e:
        if ledger_id:
            release_ledger_quota(ledger_id)
        if record_id:
            update_analysis_record(record_id, {"status": "failed_upstream", "error_message": "Internal error"})
        logging.exception("Analysis failed")
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Analysis failed. Please try again.",
            retryable=True,
            original_error=e,
        ) from e


@api_bp.route("/api/history", methods=["GET"])
@require_auth
def history(user):
    """Return analysis history (placeholder)."""
    return jsonify({"success": True, "data": {"items": [], "total": 0}}), 200


@api_bp.route("/api/analysis/<analysis_id>", methods=["GET"])
@require_auth
def analysis_detail(user, analysis_id):
    """Return a single analysis record by ID (placeholder)."""
    return (
        jsonify(
            {
                "success": False,
                "error": {
                    "code": ErrorCode.NOT_FOUND.value,
                    "message": "Analysis not found.",
                    "retryable": False,
                    "request_id": "",
                },
            }
        ),
        404,
    )


# ---- Legacy OpenAI Query ----


@api_bp.route("/query", methods=["POST"])
def query_openai_route():
    """Legacy OpenAI query endpoint."""
    from app.openai_handler import parse_args, query_openai

    try:
        data = request.get_json(force=True, silent=True)
        if data is None:
            return jsonify({"error": "Invalid JSON"}), 400
        user_prompt = data.get("prompt")

        if not user_prompt:
            return jsonify({"error": "Prompt is required"}), 400

        function_name, args, kwargs = parse_args(query_openai(user_prompt, ""))
        if function_name is None:
            return jsonify({"error": "Failed to parse response"}), 500

        # Note: FUNCTION_ROUTER was removed from openai_handler.
        # The legacy endpoint needs to be updated separately.
        return jsonify({"response": "Legacy endpoint requires update"}), 200

    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        return jsonify({"error": f"{str(e)}"}), 500


# ---- Index ----


@api_bp.route("/")
def index():
    """Renders the chat UI."""
    return render_template("chat_ui.html")
