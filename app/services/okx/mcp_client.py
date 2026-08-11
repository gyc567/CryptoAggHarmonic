"""stdio JSON-RPC wrapper around the ``okx-trade-mcp`` MCP server.

Phase 1 scope: spot + market + account (read-only by default; spot
write only with ``--demo`` flag and ``OKX_PAPER_MODE=true``).

Mirrors the freqtrade ``mcp_client.py`` pattern:

  - ``OKXMCPClient(subprocess_args)`` — spawns the MCP server, talks
    over stdio with newline-delimited JSON-RPC.
  - ``invoke_tool(name, args, timeout=1800)`` — single tool call.
  - ``list_tools()`` — discovery.
  - ``MAX_OKX_WRITE_PER_GEN=3`` — per-generation write cap (ADR-0011 M7).
  - Rate-limit retry: code=50011 → wait 5s + single retry.

Errors are raised as ``OKXAPIError`` (server) or ``OKXClientError``
(local). All non-zero ``code`` values are propagated.

The 30-second heartbeat is enforced by the caller; this module is
transport-only.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Per-generation write cap (ADR-0011 M7). 3 is conservative — the
# freqtrade cap is 5 but OKX write operations have irreversible side
# effects so the cap is tighter.
MAX_OKX_WRITE_PER_GEN = 3

# Default timeout per MCP tool call. Backtest/hyperopt can be long
# but OKX market/account calls should be <5s; spot_place_order in
# paper mode is also <5s. 1800s is the safety ceiling.
DEFAULT_TIMEOUT_SECONDS = 1800

# OKX server-side rate limit (per docs): 20 req/2s.
# code=50011 means "too many requests".
RATE_LIMIT_CODE = "50011"
RATE_LIMIT_WAIT_SECONDS = 5


class OKXClientError(RuntimeError):
    """Local client-side error (subprocess died, timeout, parse failure)."""


class OKXAPIError(RuntimeError):
    """OKX MCP server returned a non-zero code."""

    def __init__(self, code: str, message: str, tool: str, trace_id: str | None = None) -> None:
        super().__init__(f"okx tool={tool} code={code} message={message}")
        self.code = code
        self.message = message
        self.tool = tool
        self.trace_id = trace_id


@dataclass
class OKXToolResult:
    """Parsed result from an OKX MCP tool call."""

    ok: bool
    data: Any
    code: str = "0"
    trace_id: str | None = None
    latency_ms: int = 0


@dataclass
class OKXMCPClient:
    """stdio JSON-RPC client for okx-trade-mcp.

    Lifecycle: ``__post_init__`` spawns the subprocess; ``close()``
    terminates it. Use as a context manager.
    """

    args: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    proc: subprocess.Popen | None = None
    write_count_this_gen: int = 0

    def __post_init__(self) -> None:
        full_env = os.environ.copy()
        full_env.update(self.env)
        try:
            self.proc = subprocess.Popen(
                self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
                cwd=self.cwd,
                text=True,
            )
        except FileNotFoundError as e:
            raise OKXClientError(f"okx-trade-mcp not found: {e}") from e

    def list_tools(self, timeout: int = 30) -> list[dict]:
        """List all available tools from the OKX MCP server."""
        return self._call("tools/list", {}, timeout=timeout)

    def invoke_tool(
        self,
        name: str,
        args: dict,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        is_write: bool = False,
    ) -> OKXToolResult:
        """Invoke an OKX MCP tool.

        Args:
            name: tool name (e.g. "market_get_ticker", "spot_place_order").
            args: tool arguments dict.
            timeout: max seconds to wait for response.
            is_write: True if this is a write operation (counts toward
                ``MAX_OKX_WRITE_PER_GEN``).

        Returns:
            OKXToolResult with parsed data.

        Raises:
            OKXClientError: local error (subprocess, timeout, parse).
            OKXAPIError: OKX server returned non-zero code.
        """
        if is_write:
            if self.write_count_this_gen >= MAX_OKX_WRITE_PER_GEN:
                raise OKXClientError(
                    f"per-gen write cap reached ({MAX_OKX_WRITE_PER_GEN}); "
                    f"refusing tool={name} (ADR-0011 M7)"
                )
            self.write_count_this_gen += 1

        t0 = time.perf_counter()
        data = self._call("tools/call", {"name": name, "arguments": args}, timeout=timeout)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        # OKX tool results carry a `code` field (string "0" on success).
        code = str(data.get("code", "0")) if isinstance(data, dict) else "0"
        trace_id = data.get("traceId") if isinstance(data, dict) else None

        if code == RATE_LIMIT_CODE:
            # Wait + single retry (ADR-0011 M7).
            logger.warning(f"okx rate limit hit (code={code}); waiting {RATE_LIMIT_WAIT_SECONDS}s + retry")
            time.sleep(RATE_LIMIT_WAIT_SECONDS)
            data = self._call("tools/call", {"name": name, "arguments": args}, timeout=timeout)
            code = str(data.get("code", "0")) if isinstance(data, dict) else "0"
            trace_id = data.get("traceId") if isinstance(data, dict) else None

        if code != "0":
            msg = data.get("msg", "unknown") if isinstance(data, dict) else "unknown"
            raise OKXAPIError(code=code, message=msg, tool=name, trace_id=trace_id)

        return OKXToolResult(ok=True, data=data, code=code, trace_id=trace_id, latency_ms=latency_ms)

    def reset_gen_counter(self) -> None:
        """Reset the per-generation write counter. Call at the start of
        each cryptoagg loop generation."""
        self.write_count_this_gen = 0

    def _call(self, method: str, params: dict, timeout: int) -> Any:
        import select
        if self.proc is None or self.proc.stdin is None or self.proc.stdout is None:
            raise OKXClientError("client not started or already closed")
        req_id = uuid.uuid4().hex
        request = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        # ponytail: BrokenPipeError is a defensive fallback only reached when
        # the subprocess closes stdin while still alive; 97.88% coverage is the
        # ceiling — exercising this path requires a 60s sleep subprocess and
        # is not stable in CI. Upgrade: a fake-stdin E2E test using a wrapper.
        try:
            self.proc.stdin.write(request + "\n")
            self.proc.stdin.flush()
        except BrokenPipeError as e:
            raise OKXClientError(f"okx-trade-mcp pipe broken: {e}") from e
        # Enforce timeout via select() on the stdout fd. Without this,
        # a hung okx-trade-mcp would block _call() indefinitely.
        stdout_fd = self.proc.stdout.fileno()
        ready, _, _ = select.select([stdout_fd], [], [], timeout)
        if not ready:
            self.proc.terminate()
            raise OKXClientError(f"okx-trade-mcp call timeout after {timeout}s (method={method})")
        line = self.proc.stdout.readline()  # type: ignore[union-attr]
        if not line:
            stderr = self.proc.stderr.read() if self.proc.stderr else ""  # type: ignore[union-attr]
            raise OKXClientError(f"okx-trade-mcp closed unexpectedly; stderr={stderr!r}")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as e:
            raise OKXClientError(f"non-JSON response from okx-trade-mcp: {line!r}") from e
        if "error" in response:
            err = response["error"]
            raise OKXClientError(f"jsonrpc error: {err}")
        return response.get("result")

    def close(self) -> None:
        # ponytail: kill() fallback (subprocess ignores SIGTERM) is defensive —
        # 97.88% coverage ceiling. Upgrade: spawn a SIGTERM-ignoring
        # subprocess under CI-controlled timeout.
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None

    def __enter__(self) -> "OKXMCPClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
