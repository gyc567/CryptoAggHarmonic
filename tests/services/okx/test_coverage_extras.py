"""Additional tests to reach 100% coverage on app/services/okx/."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.okx.audit import AuditLog
from app.services.okx.data_source import OKXMarketData
from app.services.okx.executor import OKXExecutor
from app.services.okx.handshake import OKXFill, write_fill_to_history
from app.services.okx.mcp_client import (
    OKXAPIError,
    OKXClientError,
    OKXMCPClient,
    OKXToolResult,
)


class TestAuditReadTodayNoFile:
    def test_read_today_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        log = AuditLog(root=tmp_path / "audit-no-file")
        assert log.read_today() == []


class TestExecutorPaperDefaultFromEnv:
    def test_paper_default_true_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OKX_PAPER_MODE", raising=False)
        monkeypatch.delenv("OKX_ALLOW_LIVE", raising=False)
        audit = AuditLog(root=tmp_path / "audit")
        client = MagicMock()
        executor = OKXExecutor(client=client, audit=audit)
        assert executor.paper is True
        assert executor.allow_live is False

    def test_paper_default_false_via_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OKX_PAPER_MODE", "false")
        audit = AuditLog(root=tmp_path / "audit")
        client = MagicMock()
        executor = OKXExecutor(client=client, audit=audit)
        assert executor.paper is False



class TestDataSourceEmptyPaths:
    def test_funding_rate_empty_raises(self) -> None:
        client = MagicMock()
        client.invoke_tool.return_value = OKXToolResult(
            ok=True, data={"data": []}, code="0", trace_id="t", latency_ms=10,
        )
        ds = OKXMarketData(client)
        with pytest.raises(ValueError, match="funding rate returned empty"):
            ds.get_funding_rate("BTC-USDT-SWAP")

    def test_mark_price_empty_raises(self) -> None:
        client = MagicMock()
        client.invoke_tool.return_value = OKXToolResult(
            ok=True, data={"data": []}, code="0", trace_id="t", latency_ms=10,
        )
        ds = OKXMarketData(client)
        with pytest.raises(ValueError, match="mark price returned empty"):
            ds.get_mark_price("BTC-USDT-SWAP")


class TestHandshakeErrorHandling:
    def test_append_history_unexpected_error_leaves_outbox(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.services.okx import handshake
        root = tmp_path / "loop_state"
        (root / "HISTORY.jsonl.outbox").mkdir(parents=True)
        monkeypatch.setattr(handshake, "_LOOP_STATE_ROOT", root, raising=False)
        monkeypatch.setattr(handshake, "HISTORY_PATH", root / "HISTORY.jsonl", raising=False)
        monkeypatch.setattr(handshake, "OUTBOX_DIR", root / "HISTORY.jsonl.outbox", raising=False)

        def fake_append(record, root=None):  # type: ignore[no-untyped-def,unused-argument]
            raise OSError("simulated I/O failure")

        monkeypatch.setattr(handshake, "append_history", fake_append)
        fill = OKXFill(
            uuid="errfill0001", instId="BTC-USDT", side="buy",
            fillPx=65000.0, fillSz=0.001, fee=0.05,
            ts="2026-08-11T00:00:00Z", ordId="1", clOrdId="OKX-LOOP-test",
            paper=True, salt_version=1,
        )
        write_fill_to_history(fill)
        outbox = root / "HISTORY.jsonl.outbox"
        leftovers = [f for f in outbox.iterdir() if f.name == "errfill0001.json"]
        assert leftovers, "outbox entry should be left for retry on I/O failure"


# --- mcp_client coverage ---

_ECHO_PY = r"""
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try: req = json.loads(line)
    except: continue
    resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": {"code": "0", "data": {}}}
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()
"""

_API_ERROR_PY = r"""
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try: req = json.loads(line)
    except: continue
    resp = {"jsonrpc": "2.0", "id": req.get("id"),
            "result": {"code": "51020", "msg": "Order quantity invalid"}}
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()
"""

_RPC_ERROR_PY = r"""
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try: req = json.loads(line)
    except: continue
    resp = {"jsonrpc": "2.0", "id": req.get("id"),
            "error": {"code": -32601, "message": "method not found"}}
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()
"""

_BAD_JSON_PY = r"""
import sys
sys.stdout.write("not-json\n")
sys.stdout.flush()
"""

# Subprocess that traps SIGTERM and keeps running. close() must hit
# the wait(5) timeout branch and fall through to kill().
_STUCK_PY = r"""  # retained for future use
# 
import signal, time, sys
signal.signal(signal.SIGTERM, signal.SIG_IGN)
for _ in range(60):
    time.sleep(1)
# drain stdin so SIGPIPE doesn't kill us
for _ in sys.stdin: pass
"""


def _spawn(code: str) -> OKXMCPClient:
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    client = OKXMCPClient.__new__(OKXMCPClient)
    client.args = ["script"]; client.env = {}; client.cwd = None
    client.proc = proc  # type: ignore[assignment]
    client.write_count_this_gen = 0
    return client


class TestMCPClientCoverage:
    def test_post_init_spawns_subprocess(self) -> None:
        client = OKXMCPClient(args=[sys.executable, "-c", _ECHO_PY])
        try:
            assert client.proc is not None
            result = client.invoke_tool("test", {})
            assert result.ok
        finally:
            client.close()

    def test_post_init_missing_binary_raises(self) -> None:
        with pytest.raises(OKXClientError, match="okx-trade-mcp not found"):
            OKXMCPClient(args=["definitely-does-not-exist-binary-xyz"])

    def test_list_tools(self) -> None:
        client = _spawn(_ECHO_PY)
        try:
            tools = client.list_tools()
            assert isinstance(tools, dict)
        finally:
            client.close()

    def test_invoke_tool_api_error(self) -> None:
        client = _spawn(_API_ERROR_PY)
        try:
            with pytest.raises(OKXAPIError) as exc_info:
                client.invoke_tool("spot_place_order", {})
            assert exc_info.value.code == "51020"
            assert "Order quantity" in exc_info.value.message
        finally:
            client.close()

    def test_invoke_tool_rpc_error(self) -> None:
        client = _spawn(_RPC_ERROR_PY)
        try:
            with pytest.raises(OKXClientError, match="jsonrpc error"):
                client.invoke_tool("spot_place_order", {})
        finally:
            client.close()

    def test_invoke_tool_bad_json(self) -> None:
        client = _spawn(_BAD_JSON_PY)
        try:
            with pytest.raises(OKXClientError, match="non-JSON response"):
                client.invoke_tool("spot_place_order", {})
        finally:
            client.close()


    def test_context_manager(self) -> None:
        with _spawn(_ECHO_PY) as client:
            assert client.proc is not None
        assert client.proc is None

