"""MCP client for freqtrade_dev_mcp tools.

Wraps the MCP server tools with:
  - Timeout enforcement (1800s per call — ADR-0010 M9)
  - Per-generation backtest cap (5 — ADR-0010 M9)
  - Tool discovery
  - Metrics埋点 (mcp_call_timeout_total)

Usage:
    client = FreqtradeMCPClient()
    tools = client.discover_tools()
    result = await client.call_tool("backtest_strategy", strategy_name="HarmonicGartley1h", ...)
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FREQTRADE_MCP_PATH = Path(__file__).parent.parent.parent.parent / "freqtrade_dev_mcp" / "src" / "server.py"

# ADR-0010 M9 constraints
MCP_TIMEOUT_SECONDS = 1800  # 30 minutes max per call
MAX_BACKTEST_PER_GEN = 5   # cap backtest candidates per generation


@dataclass
class MCPTool:
    """Discovered MCP tool."""

    name: str
    description: str
    input_schema: dict


@dataclass
class MCPClientMetrics:
    """Metrics for MCP client calls."""

    call_total: int = 0
    timeout_total: int = 0
    error_total: int = 0

    def record_call(self, success: bool, timed_out: bool = False) -> None:
        self.call_total += 1
        if timed_out:
            self.timeout_total += 1
        elif not success:
            self.error_total += 1


@dataclass
class FreqtradeMCPClient:
    """MCP client for freqtrade_dev_mcp.

    Note: This client invokes the MCP server as a subprocess over stdio.
    The actual tool logic lives in freqtrade_dev_mcp/src/commands/.
    """

    mcp_path: Path = field(default=FREQTRADE_MCP_PATH)
    timeout_seconds: int = MCP_TIMEOUT_SECONDS
    max_backtest_per_gen: int = MAX_BACKTEST_PER_GEN

    _backtest_count: int = field(default=0, repr=False)
    _tools: list[MCPTool] | None = field(default=None, repr=False)
    metrics: MCPClientMetrics = field(default_factory=MCPClientMetrics)

    # Per-call backtrack counter for rate limiting
    _gen_backtest_count: int = field(default=0, repr=False)

    def reset_gen_counter(self) -> None:
        """Reset per-generation backtest counter (call at generation start)."""
        self._gen_backtest_count = 0

    async def discover_tools(self) -> list[MCPTool]:
        """Discover available MCP tools by calling list_tools."""
        if self._tools is not None:
            return self._tools

        result = await self._call_mcp_raw({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        if isinstance(result, dict) and "tools" in result:
            self._tools = [MCPTool(name=t["name"], description=t.get("description", ""), input_schema=t.get("inputSchema", {})) for t in result["tools"]]
        else:
            self._tools = []
        return self._tools

    async def call_tool(self, tool_name: str, **kwargs: Any) -> dict[str, Any]:
        """Call an MCP tool with timeout and metrics.

        Args:
            tool_name: Name of the MCP tool (e.g. "backtest_strategy").
            **kwargs: Tool arguments.

        Returns:
            Tool result dict.

        Raises:
            asyncio.TimeoutError: If call exceeds MCP_TIMEOUT_SECONDS.
            MCPError: If tool returns an error.
        """
        # Rate limiting for backtest tools
        if tool_name in ("backtest_strategy", "hyperopt_strategy"):
            if self._gen_backtest_count >= self.max_backtest_per_gen:
                raise MCPError(f"Per-generation backtest cap ({self.max_backtest_per_gen}) reached")
            self._gen_backtest_count += 1

        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": kwargs,
            },
        }

        start = time.monotonic()
        try:
            result = await asyncio.wait_for(self._call_mcp_raw(payload), timeout=self.timeout_seconds)
            elapsed = time.monotonic() - start
            self.metrics.record_call(success=True)
            logger.info(f"MCP tool={tool_name} elapsed={elapsed:.1f}s")
            return result if isinstance(result, dict) else {"result": result}
        except asyncio.TimeoutError:
            self.metrics.record_call(success=False, timed_out=True)
            logger.error(f"MCP tool={tool_name} timed out after {self.timeout_seconds}s")
            raise

    async def _call_mcp_raw(self, payload: dict) -> Any:
        """Send a raw JSON-RPC payload to the MCP stdio server."""
        proc = await asyncio.create_subprocess_exec(
            "python",
            str(self.mcp_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=json.dumps(payload).encode(), timeout=self.timeout_seconds + 10)
        if proc.returncode != 0:
            self.metrics.record_call(success=False)
            stderr_text = stderr.decode(errors="replace")
            logger.error(f"MCP stderr: {stderr_text}")
            raise MCPError(f"MCP server exited with code {proc.returncode}: {stderr_text}")
        try:
            return json.loads(stdout.decode())
        except json.JSONDecodeError as e:
            self.metrics.record_call(success=False)
            raise MCPError(f"Invalid JSON from MCP server: {e}")


class MCPError(Exception):
    """Raised when an MCP call fails."""


# Convenience async context manager
class MCP:
    """Async context manager for FreqtradeMCPClient."""

    def __init__(self) -> None:
        self.client = FreqtradeMCPClient()

    async def __aenter__(self) -> FreqtradeMCPClient:
        await self.client.discover_tools()
        return self.client

    async def __aexit__(self, *args: Any) -> None:
        pass
