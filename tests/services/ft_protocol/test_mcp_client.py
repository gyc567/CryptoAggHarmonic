"""Tests for app.services.freqtrade.mcp_client."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.freqtrade.mcp_client import (
    MCP_TIMEOUT_SECONDS,
    MAX_BACKTEST_PER_GEN,
    MCPTool,
    MCPClientMetrics,
    FreqtradeMCPClient,
    MCPError,
)


class TestMCPTool:
    def test_mcp_tool_dataclass(self) -> None:
        tool = MCPTool(
            name="backtest_strategy",
            description="Run backtest",
            input_schema={"type": "object", "properties": {}},
        )
        assert tool.name == "backtest_strategy"
        assert tool.description == "Run backtest"


class TestMCPClientMetrics:
    def test_record_call_success(self) -> None:
        m = MCPClientMetrics()
        m.record_call(success=True)
        assert m.call_total == 1
        assert m.timeout_total == 0
        assert m.error_total == 0

    def test_record_call_timeout(self) -> None:
        m = MCPClientMetrics()
        m.record_call(success=False, timed_out=True)
        assert m.call_total == 1
        assert m.timeout_total == 1
        assert m.error_total == 0

    def test_record_call_error(self) -> None:
        m = MCPClientMetrics()
        m.record_call(success=False, timed_out=False)
        assert m.call_total == 1
        assert m.error_total == 1


class TestFreqtradeMCPClient:
    def test_rate_limit_counter(self) -> None:
        client = FreqtradeMCPClient()
        client.reset_gen_counter()
        assert client._gen_backtest_count == 0
        # Simulate consuming counter
        client._gen_backtest_count = 3
        assert client._gen_backtest_count == 3

    def test_constants(self) -> None:
        assert MCP_TIMEOUT_SECONDS == 1800
        assert MAX_BACKTEST_PER_GEN == 5


class TestMCPError:
    def test_mcp_error_message(self) -> None:
        err = MCPError("connection refused")
        assert str(err) == "connection refused"
