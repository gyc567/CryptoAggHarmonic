"""Tests OKXExecutor: three-gate enforcement + audit log integration."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.okx.audit import AuditLog
from app.services.okx.executor import OKXExecutor
from app.services.okx.mcp_client import OKXAPIError, OKXToolResult


def _ok_result(ord_id: str = "12345", trace_id: str = "abc") -> OKXToolResult:
    return OKXToolResult(ok=True, data={"ordId": ord_id}, code="0",
                         trace_id=trace_id, latency_ms=100)


def _make_executor(tmp_path: Path, paper: bool = True) -> tuple[OKXExecutor, AuditLog, MagicMock]:
    audit = AuditLog(root=tmp_path / "audit")
    client = MagicMock()
    return OKXExecutor(client=client, audit=audit, paper=paper), audit, client


class TestGate1UnknownTool:
    def test_unknown_tool_rejected_no_dispatch(self, tmp_path: Path) -> None:
        executor, audit, client = _make_executor(tmp_path)
        result = executor.dispatch("market_get_ticker", {"instId": "BTC-USDT"})
        assert result.gate_passed is False
        assert result.tool_result is None
        client.invoke_tool.assert_not_called()
        recs = audit.read_today()
        assert len(recs) == 1
        assert recs[0]["gate"] == "gate1_unknown_tool"
        assert recs[0]["result_code"] == "REJECTED"


class TestGate2PaperMode:
    def test_live_mode_without_allow_live_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # paper=False, no OKX_ALLOW_LIVE env → rejected.
        monkeypatch.delenv("OKX_ALLOW_LIVE", raising=False)
        executor, audit, client = _make_executor(tmp_path, paper=False)
        result = executor.dispatch("spot_place_order", {"instId": "BTC-USDT"})
        assert result.gate_passed is False
        client.invoke_tool.assert_not_called()
        recs = audit.read_today()
        assert recs[0]["gate"] == "gate2_no_allow_live"

    def test_live_mode_with_allow_live_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OKX_ALLOW_LIVE", "1")
        executor, audit, client = _make_executor(tmp_path, paper=False)
        client.invoke_tool.return_value = _ok_result()
        result = executor.dispatch("spot_place_order", {"instId": "BTC-USDT"})
        assert result.gate_passed is True
        assert result.tool_result == {"ordId": "12345"}


class TestGate3ToolGate:
    def test_tool_gate_records_mode_in_audit(self, tmp_path: Path) -> None:
        executor, audit, client = _make_executor(tmp_path, paper=True)
        client.invoke_tool.return_value = _ok_result()
        executor.dispatch("spot_place_order", {"instId": "BTC-USDT"})
        recs = audit.read_today()
        # gate3 passes silently (execution_allowed_for_tools records mode
        # but does not block; the actual dispatch log uses gate=dispatched)
        assert any(r["gate"] == "dispatched" for r in recs)
        assert recs[0]["paper"] is True


class TestDispatchedOK:
    def test_successful_dispatch(self, tmp_path: Path) -> None:
        executor, audit, client = _make_executor(tmp_path, paper=True)
        client.invoke_tool.return_value = _ok_result(ord_id="999")
        result = executor.dispatch(
            "spot_place_order",
            {"instId": "BTC-USDT", "clOrdId": "OKX-LOOP-test1234"},
            salt_version=3,
        )
        assert result.gate_passed is True
        assert result.tool_result == {"ordId": "999"}
        recs = audit.read_today()
        assert len(recs) == 1
        assert recs[0]["result_code"] == "0"
        assert recs[0]["salt_version"] == 3
        assert recs[0]["cl_ord_id"] == "OKX-LOOP-test1234"
        assert recs[0]["trace_id"] == "abc"
        # Per-gen counter must have incremented
        assert client.invoke_tool.call_args.kwargs.get("is_write") is True


class TestDispatchedAPIError:
    def test_api_error_still_audited(self, tmp_path: Path) -> None:
        executor, audit, client = _make_executor(tmp_path, paper=True)
        client.invoke_tool.side_effect = OKXAPIError(
            code="51020", message="Order quantity invalid",
            tool="spot_place_order", trace_id="trace-xyz",
        )
        with pytest.raises(OKXAPIError):
            executor.dispatch("spot_place_order", {"instId": "BTC-USDT"})
        recs = audit.read_today()
        assert len(recs) == 1
        assert recs[0]["result_code"] == "51020"
        assert recs[0]["gate"] == "dispatched_api_error"
        assert recs[0]["trace_id"] == "trace-xyz"


class TestSaltVersionTrace:
    def test_salt_version_propagated(self, tmp_path: Path) -> None:
        executor, _, client = _make_executor(tmp_path, paper=True)
        client.invoke_tool.return_value = _ok_result()
        executor.dispatch("spot_place_order", {}, salt_version=42)
        recs = executor.audit.read_today()
        assert recs[0]["salt_version"] == 42
