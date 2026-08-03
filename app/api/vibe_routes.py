"""API routes for the AI Trading Assistant (Vibe) module."""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, Response, request
from redis import ConnectionError as RedisConnectionError
from redis import Redis
from rq import Queue
from rq.command import send_stop_job_command

from app.api.auth import is_local_dev_mode, require_auth
from app.api.responses import error as _error
from app.api.responses import success as _success
from app.api.validation import parse_request
from app.domain.vibe_schemas import (
    CreateSessionRequest,
    SendMessageRequest,
    ToolRequest,
)
from app.infra.supabase_client import (
    consume_ledger_quota,
    log_audit_event,
    release_ledger_quota,
    reserve_user_quota,
)
from app.infra.vibe_event_store import VibeEventStore
from app.infra.vibe_session_store import VibeSessionStore
from app.infra.vibe_trace_store import VibeTraceStore
from app.factory import get_orchestrator
from app.services.vibe.cancellation import cancel_run as signal_cancel_run
from app.services.vibe.cancellation import register_run
from app.services.vibe.runner import run_vibe_agent
from app.services.vibe.tools import create_default_registry
from app.services.vibe.tools.base import ToolRuntime

logger = logging.getLogger(__name__)

vibe_bp = Blueprint("vibe", __name__, url_prefix="/api/vibe")


def _get_redis() -> Redis:
    return Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


def _get_queue() -> Queue:
    return Queue("vibe", connection=_get_redis())


def _get_session_store() -> VibeSessionStore:
    return VibeSessionStore()


def _get_event_store() -> VibeEventStore:
    return VibeEventStore()


def _get_trace_store() -> VibeTraceStore:
    return VibeTraceStore()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- Sessions ----


@vibe_bp.route("/sessions", methods=["POST"])
@require_auth
def create_session(user):
    """Create a new vibe session."""
    req, err = parse_request(CreateSessionRequest, request.get_json(silent=True))
    if err is not None:
        return err

    store = _get_session_store()
    session = store.create_session(
        user_id=user["id"],
        title=req.title,
        context=req.context,
    )
    return _success(session)


@vibe_bp.route("/sessions", methods=["GET"])
@require_auth
def list_sessions(user):
    """List vibe sessions for the current user."""
    limit = min(int(request.args.get("limit", 50)), 100)
    offset = int(request.args.get("offset", 0))
    store = _get_session_store()
    sessions = store.list_sessions(user_id=user["id"], limit=limit, offset=offset, status="active")
    return _success({"items": sessions, "total": len(sessions)})


@vibe_bp.route("/sessions/<session_id>", methods=["GET"])
@require_auth
def get_session(user, session_id):
    """Get a single session."""
    store = _get_session_store()
    session = store.get_session(session_id, user["id"])
    if not session:
        return _error("NOT_FOUND", "会话不存在", status=404)
    return _success(session)


@vibe_bp.route("/sessions/<session_id>", methods=["DELETE"])
@require_auth
def delete_session(user, session_id):
    """Archive a session."""
    store = _get_session_store()
    if not store.get_session(session_id, user["id"]):
        return _error("NOT_FOUND", "会话不存在", status=404)
    store.archive_session(session_id, user["id"])
    return _success({"id": session_id, "status": "deleted"})


# ---- Messages / Runs ----


@vibe_bp.route("/sessions/<session_id>/messages", methods=["POST"])
@require_auth
def send_message(user, session_id):
    """Send a message and start an agent run."""
    user_id = user["id"]
    req, err = parse_request(SendMessageRequest, request.get_json(silent=True))
    if err is not None:
        return err

    store = _get_session_store()
    session = store.get_session(session_id, user_id)
    if not session:
        return _error("NOT_FOUND", "会话不存在", status=404)

    # Reserve quota.
    run_id = str(uuid.uuid4())
    ledger_id = None
    if not is_local_dev_mode():
        reserved, _, ledger_id = reserve_user_quota(user_id, run_id, units=1)
        if not reserved:
            return _error("QUOTA_EXCEEDED", "每日额度已用完", status=429, retryable=False)

    # Create run record.
    run_record = {
        "id": run_id,
        "session_id": session_id,
        "user_id": user_id,
        "status": "running",
        "user_prompt": req.content,
        "created_at": _now(),
    }
    store.create_run(run_record)

    # Enqueue agent job (or run synchronously in a thread if Redis is unavailable).
    enqueued = _enqueue_or_run_sync(session_id, run_id, user_id, req.content, ledger_id)
    if not enqueued:
        store.update_run(run_id, {"status": "failed", "error": "无法启动运行"})
        if ledger_id:
            release_ledger_quota(ledger_id)
        return _error("INTERNAL_ERROR", "启动助手失败，请重试", retryable=True)

    # If SSE is requested, stream events.
    if request.headers.get("Accept", "").startswith("text/event-stream"):
        return _stream_events(run_id, user_id)

    return _success({"run_id": run_id, "status": "running"})


@vibe_bp.route("/runs/<run_id>", methods=["GET"])
@require_auth
def get_run(user, run_id):
    """Get run metadata."""
    store = _get_session_store()
    run = store.get_run(run_id, user["id"])
    if not run:
        return _error("NOT_FOUND", "运行记录不存在", status=404)
    return _success(run)


@vibe_bp.route("/runs/<run_id>/events", methods=["GET"])
@require_auth
def get_run_events(user, run_id):
    """Get run events (polling) or SSE stream."""
    store = _get_session_store()
    run = store.get_run(run_id, user["id"])
    if not run:
        return _error("NOT_FOUND", "运行记录不存在", status=404)

    if request.headers.get("Accept", "").startswith("text/event-stream"):
        return _stream_events(run_id, user["id"])

    after = request.args.get("after")
    limit = min(int(request.args.get("limit", 50)), 200)
    event_store = _get_event_store()
    events = event_store.get_events(run_id, after_event_id=after, limit=limit)
    return _success({"run_id": run_id, "status": run.get("status"), "events": events, "has_more": False})


@vibe_bp.route("/runs/<run_id>", methods=["DELETE"])
@require_auth
def cancel_run(user, run_id):
    """Cancel a running vibe job."""
    store = _get_session_store()
    run = store.get_run(run_id, user["id"])
    if not run:
        return _error("NOT_FOUND", "运行记录不存在", status=404)

    try:
        queue = _get_queue()
        job = queue.fetch_job(run_id)
        if job:
            job.cancel()
            try:
                send_stop_job_command(queue.connection, run_id)
            except Exception as e:
                logger.warning("Failed to send stop job command for %s: %s", run_id, e)
        # Signal sync-thread fallback or RQ worker via Redis/local event.
        signal_cancel_run(run_id)
        store.cancel_run(run_id, user["id"])
    except Exception as e:
        logger.warning("Failed to cancel run %s: %s", run_id, e)

    return _success({"run_id": run_id, "status": "cancelled"})


@vibe_bp.route("/runs/<run_id>/trace", methods=["GET"])
@require_auth
def get_run_trace(user, run_id):
    """Get run trace (user or admin only)."""
    trace_store = _get_trace_store()
    trace = trace_store.get_trace(run_id, user["id"])
    if trace is None:
        return _error("NOT_FOUND", "Trace 不存在", status=404)
    return _success(trace)


# ---- Tools ----

# Tools that are safe to invoke directly through the /tools/<name> endpoint.
# Write/side-effect tools must be invoked by the orchestrator so that system
# prompts, tool-chain ordering and safety constraints are enforced.
_DIRECT_TOOL_ALLOWLIST = {"explain_market", "position_check"}


@vibe_bp.route("/tools/<tool_name>", methods=["POST"])
@require_auth
def invoke_tool(user, tool_name):
    """Invoke a single read-only tool directly.

    Mirrors send_message quota handling: reserve 1 unit, consume on success,
    release on failure. Subject to the user's daily analysis quota.

    Only tools in _DIRECT_TOOL_ALLOWLIST may be invoked here. Side-effect
    tools (e.g. save_to_journal, analyze_harmonic) must go through the
    orchestrator so that system prompts and safety constraints apply.
    """
    user_id = user["id"]
    req, err = parse_request(ToolRequest, request.get_json(silent=True))
    if err is not None:
        return err

    if tool_name not in _DIRECT_TOOL_ALLOWLIST:
        return _error(
            "FORBIDDEN",
            f"工具 {tool_name} 不允许直接调用，请通过对话流程使用。",
            status=403,
            retryable=False,
        )

    invoke_id = str(uuid.uuid4())
    ledger_id = None
    if not is_local_dev_mode():
        reserved, _, ledger_id = reserve_user_quota(user_id, invoke_id, units=1)
        if not reserved:
            return _error("QUOTA_EXCEEDED", "每日额度已用完", status=429, retryable=False)

    orchestrator_instance = get_orchestrator()
    registry = create_default_registry(orchestrator_instance)
    tool = registry.get(tool_name)
    if not tool:
        if ledger_id:
            release_ledger_quota(ledger_id)
        return _error("NOT_FOUND", f"工具不存在: {tool_name}", status=404)

    runtime = ToolRuntime(
        user_id=user_id,
        session_id="",
        run_id=invoke_id,
    )
    output = registry.execute(tool_name, req.input, runtime)
    if output.status != "completed":
        if ledger_id:
            release_ledger_quota(ledger_id)
        if output.status == "invalid_input":
            return _error("INVALID_PARAMS", output.error or "参数校验失败", status=400)
        return _error("TOOL_ERROR", output.error or "工具执行失败")

    if ledger_id:
        consume_ledger_quota(ledger_id)

    log_audit_event(
        actor_id=user_id,
        action="vibe_tool_invoked",
        target_type="tool",
        target_id=tool_name,
        details={"input": req.input},
    )
    return _success(output.data)


# ---- SSE Streaming ----


def _enqueue_or_run_sync(session_id: str, run_id: str, user_id: str, content: str, ledger_id: Optional[str] = None) -> bool:
    """Try to enqueue to RQ; fall back to a background thread if Redis is down."""
    try:
        queue = _get_queue()
        # Quick health check.
        queue.connection.ping()
        queue.enqueue(
            run_vibe_agent,
            session_id,
            run_id,
            user_id,
            content,
            ledger_id,
            job_id=run_id,
            job_timeout=int(os.getenv("VIBE_MAX_RUN_MINUTES", "5")) * 60,
        )
        return True
    except (RedisConnectionError, ConnectionError) as e:
        logger.warning("Redis/RQ unavailable (%s), falling back to synchronous thread", e)
        token = register_run(run_id)
        thread = threading.Thread(
            target=run_vibe_agent,
            args=(session_id, run_id, user_id, content, ledger_id),
            kwargs={"cancellation_token": token},
            daemon=True,
        )
        thread.start()
        return True
    except Exception:
        logger.exception("Failed to enqueue vibe job")
        return False


def _stream_events(run_id: str, user_id: str):
    """Generate an SSE stream for a run."""
    event_store = _get_event_store()
    session_store = _get_session_store()

    def generate():
        import time

        # The orchestrator publishes a typed run_started event to the event
        # store immediately after starting; SSE just mirrors the store so we
        # don't need a synthetic preamble here.

        max_empty_polls = int(os.getenv("VIBE_SSE_TIMEOUT_SECONDS", "60")) // 1
        empty_polls = 0
        # Offset into the event stream; advances per streamed event so SSE is
        # O(1) amortized instead of O(n^2).
        seen_count = 0

        while empty_polls < max_empty_polls:
            # Use offset to fetch only events that have not been streamed yet,
            # avoiding O(n^2) behaviour as the event list grows.
            events = event_store.get_events(run_id, offset=seen_count, limit=50)
            for event in events:
                seen_count += 1
                yield f"event: {event.get('type')}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

                if event.get("type") in ("done", "error"):
                    return

            # Check if run is terminal but no done/error event yet.
            if not events:
                run = session_store.get_run(run_id, user_id)
                if run and run.get("status") in ("completed", "failed", "cancelled"):
                    empty_polls += 1
                else:
                    empty_polls = 0

            time.sleep(0.5)

    return Response(generate(), mimetype="text/event-stream")
