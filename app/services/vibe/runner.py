"""RQ job runner for vibe agent."""

import logging
from typing import Optional

from app.infra.vibe_event_store import VibeEventStore
from app.infra.vibe_session_store import VibeSessionStore
from app.infra.vibe_trace_store import VibeTraceStore
from app.services.analysis import AnalysisOrchestrator
from app.services.vibe.cancellation import (
    CancellationToken,
    register_run,
    unregister_run,
)
from app.services.vibe.llm import create_llm_provider
from app.services.vibe.orchestrator import VibeOrchestrator
from app.services.vibe.tools import create_default_registry

logger = logging.getLogger(__name__)


def run_vibe_agent(
    session_id: str,
    run_id: str,
    user_id: str,
    user_prompt: str,
    ledger_id: Optional[str] = None,
    cancellation_token: Optional[CancellationToken] = None,
) -> None:
    """RQ job entry point: execute a vibe agent run."""
    logger.info("Starting vibe agent run %s for session %s", run_id, session_id)

    # Register a cancellation token that polls Redis (and a local event) if the
    # caller did not already provide one (RQ path).
    if cancellation_token is None:
        cancellation_token = register_run(run_id)

    # Build dependencies. In production these can be injected/singletons.
    llm_provider = create_llm_provider()
    orchestrator_instance = AnalysisOrchestrator()
    tool_registry = create_default_registry(orchestrator_instance)
    session_store = VibeSessionStore()
    event_store = VibeEventStore()
    trace_store = VibeTraceStore()

    orchestrator = VibeOrchestrator(
        llm_provider=llm_provider,
        tool_registry=tool_registry,
        session_store=session_store,
        event_store=event_store,
        trace_store=trace_store,
    )

    try:
        orchestrator.run(
            session_id=session_id,
            run_id=run_id,
            user_id=user_id,
            user_prompt=user_prompt,
            ledger_id=ledger_id,
            cancellation_token=cancellation_token,
        )
    finally:
        unregister_run(run_id)
    logger.info("Finished vibe agent run %s", run_id)
