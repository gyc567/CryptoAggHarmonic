"""OKX write-path with three-gate enforcement.

Three-gate model (ADR-0011 D8):

  Gate 1 — MCP startup flag: ``--modules market,account,spot --read-only``
           set in ``.claude/settings.json``; Phase 1 default. Write tools
           are simply not invokable when --read-only is set. This is
           enforced by the MCP server, not this module.

  Gate 2 — env: ``OKX_PAPER_MODE=true`` (default) or
           ``OKX_ALLOW_LIVE=1`` (explicit opt-in). Checked at
           ``executor.dispatch()`` entry.

  Gate 3 — code: ``execution_allowed_for_tools()`` from
           ``tuning_promotion`` — records the mode and includes the
           audit log directive in the response reason. Combined with
           the per-generation write cap (``MAX_OKX_WRITE_PER_GEN``).

  Gate 4 — human: ``promotion_checklist()`` evaluated OUT-OF-BAND by a
           human review of the proposed TUNING change. This module
           does NOT call ``promotion_checklist()``; the loop driver
           does. The executor just records gate status in the audit
           log.

Every write MUST go through ``executor.dispatch()`` so that the
audit log captures it. Direct ``mcp_client.invoke_tool(is_write=True)``
bypasses the audit log and is FORBIDDEN by code review (the
executor module is the single entry point).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from app.loop.tuning_promotion import (
    execution_allowed_for_tools,
    is_live_execution_tool,
)

from .audit import AuditLog
from .mcp_client import OKXAPIError, OKXMCPClient

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    """Result of an OKX write dispatch."""

    tool: str
    paper: bool
    audit_record: dict  # the audit log entry written (or rejected)
    tool_result: Any = None  # None when gate failed
    gate_passed: bool = False


class OKXExecutor:
    """Single entry point for OKX write operations.

    Usage:

        executor = OKXExecutor(client=client, audit=audit, paper=True)
        result = executor.dispatch("spot_place_order", {"instId": "BTC-USDT", ...})
        if not result.gate_passed:
            # log/raise; nothing reached OKX
            ...
    """

    def __init__(self, client: OKXMCPClient, audit: AuditLog, paper: bool | None = None) -> None:
        self.client = client
        self.audit = audit
        # Resolve paper mode from env if not explicit.
        if paper is None:
            paper = os.environ.get("OKX_PAPER_MODE", "true").lower() in ("1", "true", "yes")
        self.paper = paper
        # Allow-live must be explicit env (defense in depth).
        self.allow_live = os.environ.get("OKX_ALLOW_LIVE", "").lower() in ("1", "true", "yes")

    def dispatch(self, tool: str, args: dict, salt_version: int = 1) -> DispatchResult:
        """Dispatch an OKX write tool, going through all three gates.

        Args:
            tool: MCP tool name (e.g. "spot_place_order").
            args: tool arguments.
            salt_version: ``app.config.tuning.TUNING.salt_version`` at
                dispatch time. Recorded in audit log for traceability.

        Returns:
            DispatchResult with audit record + tool result (if gates
            passed). ``gate_passed=False`` means nothing was sent to
            OKX.
        """
        # Gate 1: tool must be a known write tool (read tools go through
        # data_source, not executor).
        if not is_live_execution_tool(tool):
            record = self.audit.build_record(
                tool=tool, args=args, salt_version=salt_version,
                paper=self.paper, gate="gate1_unknown_tool",
                result_code="REJECTED", latency_ms=0, trace_id=None,
                cl_ord_id=args.get("clOrdId") if isinstance(args, dict) else None,
            )
            self.audit.write(record)
            return DispatchResult(tool=tool, paper=self.paper, audit_record=record, gate_passed=False)

        # Gate 2: paper mode enforcement.
        if not self.paper and not self.allow_live:
            record = self.audit.build_record(
                tool=tool, args=args, salt_version=salt_version,
                paper=False, gate="gate2_no_allow_live",
                result_code="REJECTED", latency_ms=0, trace_id=None,
                cl_ord_id=args.get("clOrdId") if isinstance(args, dict) else None,
            )
            self.audit.write(record)
            return DispatchResult(tool=tool, paper=False, audit_record=record, gate_passed=False)

        # Gate 3: code-level tool gate (records mode, doesn't block).
        # ponytail: gate3 fail branch is defensive — only reachable when
        # tuning_promotion.execution_allowed_for_tools returns (False, ...).
        # The normal flow returns (True, mode) so this branch is not covered
        # by functional tests. 97.88% coverage ceiling. Upgrade: a test
        # that monkeypatches the function to force (False, ...).
        ok, reason = execution_allowed_for_tools([tool], self.paper)
        if not ok:
            record = self.audit.build_record(
                tool=tool, args=args, salt_version=salt_version,
                paper=self.paper, gate="gate3_tool_blocked",
                result_code="REJECTED", latency_ms=0, trace_id=None,
                cl_ord_id=args.get("clOrdId") if isinstance(args, dict) else None,
            )
            record["gate_reason"] = reason  # surface the reason in the audit trail
            self.audit.write(record)
            return DispatchResult(tool=tool, paper=self.paper, audit_record=record, gate_passed=False)

        # All gates passed; dispatch.
        cl_ord_id = args.get("clOrdId") if isinstance(args, dict) else None
        try:
            tool_result = self.client.invoke_tool(tool, args, is_write=True)
            record = self.audit.build_record(
                tool=tool, args=args, salt_version=salt_version,
                paper=self.paper, gate="dispatched",
                result_code=tool_result.code,
                latency_ms=tool_result.latency_ms,
                trace_id=tool_result.trace_id,
                cl_ord_id=cl_ord_id,
            )
            self.audit.write(record)
            return DispatchResult(
                tool=tool, paper=self.paper, audit_record=record,
                tool_result=tool_result.data, gate_passed=True,
            )
        except OKXAPIError as e:
            record = self.audit.build_record(
                tool=tool, args=args, salt_version=salt_version,
                paper=self.paper, gate="dispatched_api_error",
                result_code=e.code,
                latency_ms=0, trace_id=e.trace_id,
                cl_ord_id=cl_ord_id,
            )
            self.audit.write(record)
            raise
