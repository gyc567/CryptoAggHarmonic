"""Tests for the new OKX tool-gate APIs in tuning_promotion.

Path-level gate (is_live_tuning_path / promotion_allowed_for_files /
promotion_checklist) is intentionally NOT touched — covered by
tests/services/freqtrade/test_promotion_guard.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.loop.tuning_promotion import (
    OKX_WRITE_TOOLS,
    execution_allowed_for_tools,
    is_live_execution_tool,
)


class TestIsLiveExecutionTool:
    def test_spot_place_order_is_write(self) -> None:
        assert is_live_execution_tool("spot_place_order") is True

    def test_market_get_ticker_is_not_write(self) -> None:
        assert is_live_execution_tool("market_get_ticker") is False

    def test_account_get_balance_is_not_write(self) -> None:
        assert is_live_execution_tool("account_get_balance") is False

    def test_account_transfer_is_write(self) -> None:
        assert is_live_execution_tool("account_transfer") is True

    def test_unknown_tool_returns_false_conservative(self) -> None:
        # Unknown tool names don't block; they fall through to the
        # MCP server's --read-only gate.
        assert is_live_execution_tool("future_module_unknown_tool") is False

    def test_swap_set_leverage_is_write(self) -> None:
        assert is_live_execution_tool("swap_set_leverage") is True

    def test_write_tools_set_is_frozen(self) -> None:
        assert isinstance(OKX_WRITE_TOOLS, frozenset)
        assert len(OKX_WRITE_TOOLS) >= 20


class TestExecutionAllowedForTools:
    def test_no_write_tools_passes(self) -> None:
        ok, reason = execution_allowed_for_tools(["market_get_ticker", "account_get_balance"], paper=True)
        assert ok is True
        assert "no write tools" in reason

    def test_paper_mode_records_mode(self) -> None:
        ok, reason = execution_allowed_for_tools(["spot_place_order"], paper=True)
        assert ok is True
        assert "paper mode" in reason
        assert "spot_place_order" in reason

    def test_live_mode_records_mode(self) -> None:
        ok, reason = execution_allowed_for_tools(["spot_place_order"], paper=False)
        assert ok is True
        assert "live mode" in reason

    def test_mixed_passes_through(self) -> None:
        ok, _ = execution_allowed_for_tools(
            ["market_get_ticker", "spot_place_order"], paper=True
        )
        assert ok is True

    def test_invalid_args_type_rejected(self) -> None:
        ok, reason = execution_allowed_for_tools("not-a-list", paper=True)  # type: ignore[arg-type]
        assert ok is False
        assert "must be list" in reason

    def test_invalid_paper_type_rejected(self) -> None:
        ok, reason = execution_allowed_for_tools([], paper="yes")  # type: ignore[arg-type]
        assert ok is False
        assert "must be bool" in reason

    def test_empty_list_passes(self) -> None:
        ok, reason = execution_allowed_for_tools([], paper=True)
        assert ok is True


class TestPathLevelAPIsUnchanged:
    """Confirm we did NOT modify the existing 3 path-gate APIs."""

    def test_is_live_tuning_path_still_present(self) -> None:
        from app.loop.tuning_promotion import is_live_tuning_path
        assert is_live_tuning_path("app/config/tuning.py") is True

    def test_promotion_allowed_for_files_still_present(self) -> None:
        from app.loop.tuning_promotion import promotion_allowed_for_files
        ok, _ = promotion_allowed_for_files(["app/services/freqtrade/translator.py"])
        assert ok is True

    def test_promotion_checklist_still_present(self) -> None:
        from app.loop.tuning_promotion import promotion_checklist
        steps = promotion_checklist()
        assert isinstance(steps, list)
        # The original 4 items (drawdown, Calmar, Shadow, salt_version) are present.
        full = "\n".join(steps)
        assert "drawdown" in full.lower()
        assert "Calmar" in full
        assert "Shadow" in full
        assert "salt_version" in full
