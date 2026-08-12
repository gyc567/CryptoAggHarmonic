"""Tests for the binance market-data gate (ADR-0013).

Extends the existing promotion guard tests; mirrors the OKX pattern
but for read-only binance market tools.
"""

from __future__ import annotations

import pytest

from app.loop.tuning_promotion import (
    BINANCE_MARKET_TOOLS,
    is_market_data_tool,
    market_data_allowed_for_tools,
)


def test_is_market_data_tool_known() -> None:
    for name in (
        "futures-usds_mark-price",
        "futures-usds_open-interest",
        "futures-usds_get-funding-rate-history",
    ):
        assert is_market_data_tool(name), f"expected {name!r} to be market data"


def test_is_market_data_tool_unknown_returns_false() -> None:
    """Unknown names return False — conservative."""
    assert not is_market_data_tool("spot_place_order")
    assert not is_market_data_tool("totally_made_up")
    assert not is_market_data_tool("")


def test_is_market_data_tool_never_returns_true_for_write() -> None:
    """Cross-check: no OKX write tool should ever be classified as market data."""
    from app.loop.tuning_promotion import OKX_WRITE_TOOLS

    for name in OKX_WRITE_TOOLS:
        assert not is_market_data_tool(name), (
            f"{name!r} is in OKX_WRITE_TOOLS but matched market data; "
            f"allowlist overlap is a security bug"
        )


def test_market_data_allowed_for_tools_accepts_known() -> None:
    ok, reason = market_data_allowed_for_tools(["futures-usds_mark-price"])
    assert ok is True
    assert "read-only" in reason


def test_market_data_allowed_for_tools_rejects_unknown() -> None:
    ok, reason = market_data_allowed_for_tools(
        ["futures-usds_mark-price", "spot_place_order"]
    )
    assert ok is False
    assert "spot_place_order" in reason


def test_market_data_allowed_for_tools_empty_list() -> None:
    ok, reason = market_data_allowed_for_tools([])
    assert ok is True
    assert "(empty)" in reason


def test_market_data_allowed_for_tools_wrong_type() -> None:
    ok, reason = market_data_allowed_for_tools("not-a-list")  # type: ignore[arg-type]
    assert ok is False
    assert "must be list" in reason


def test_market_data_allowed_for_tools_none_input() -> None:
    ok, reason = market_data_allowed_for_tools(None)  # type: ignore[arg-type]
    assert ok is False
    assert "must be list" in reason


def test_allowlist_is_frozenset() -> None:
    """Mutation of the allowlist would silently weaken the gate."""
    assert isinstance(BINANCE_MARKET_TOOLS, frozenset)


def test_allowlist_no_overlap_with_okx_writes() -> None:
    """Defense in depth: a write tool name MUST NOT appear in the market allowlist."""
    from app.loop.tuning_promotion import OKX_WRITE_TOOLS

    overlap = BINANCE_MARKET_TOOLS & OKX_WRITE_TOOLS
    assert overlap == frozenset(), f"allowlist overlap: {overlap}"


def test_market_data_tools_is_at_least_three_endpoints() -> None:
    """If a future cleanup removes too many, fail loud."""
    assert len(BINANCE_MARKET_TOOLS) >= 3