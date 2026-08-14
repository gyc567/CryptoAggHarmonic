"""
Parity test: app/strategies/ <-> freqtrade_dev_mcp/user_data/strategies/

Phase A of ``docs/plans/freqtrade-strategy-bidirectional-compat.md``
establishes the new authoritative location for FreqTrade strategy
files at ``app/strategies/`` and turns the freqtrade clone's
``user_data/strategies/`` into a symlink pointing there.

This test pins the invariant:
  - ``app/strategies/trend_rsi_strategy.py`` exists as a real file
  - ``freqtrade_dev_mcp/user_data/strategies`` is a symlink
  - ``freqtrade_dev_mcp/user_data/strategies`` resolves to ``app/strategies``
  - Reading the strategy file through either path yields the same bytes
  - The strategy file declares the ``TrendRSI`` class

ponytail: this test enforces the new single-truth layout. The ceiling
is Phase C (``engine=freqtrade`` default + delete old strategy_core).
Upgrade path is in docs/plans/freqtrade-strategy-bidirectional-compat.md
section 6.3.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = REPO_ROOT / "app" / "strategies"
CORE_FILE = CORE_DIR / "trend_rsi_strategy.py"
FREQ_DIR = REPO_ROOT / "freqtrade_dev_mcp" / "user_data" / "strategies"
FREQ_FILE = FREQ_DIR / "trend_rsi_strategy.py"


def test_app_strategies_directory_exists() -> None:
    """Phase A creates ``app/strategies/`` as the new source of truth."""
    assert CORE_DIR.is_dir(), f"missing authoritative dir: {CORE_DIR}"


def test_app_strategies_holds_trend_rsi_strategy() -> None:
    """The strategy file must live in ``app/strategies/``."""
    assert CORE_FILE.is_file(), f"missing strategy file: {CORE_FILE}"


def test_freqtrade_strategies_dir_is_symlink() -> None:
    """
    ``freqtrade_dev_mcp/user_data/strategies/`` must be a symlink,
    not a real directory, so the two paths cannot drift.
    """
    if not FREQ_DIR.exists():
        pytest.skip(
            "freqtrade_dev_mcp submodule not checked out; "
            "symlink invariant can only be verified when the submodule is present"
        )
    assert FREQ_DIR.is_symlink(), (
        f"expected {FREQ_DIR} to be a symlink, "
        f"but it is a real directory (drift risk)"
    )


def test_freqtrade_strategies_symlink_target() -> None:
    """The symlink must point to ``app/strategies/``."""
    if not FREQ_DIR.is_symlink():
        pytest.skip("freqtrade strategies dir is not a symlink yet")
    target = os.readlink(FREQ_DIR)
    expected = os.path.relpath(CORE_DIR, FREQ_DIR.parent)
    assert target == expected, (
        f"symlink target mismatch: {target!r} != {expected!r}"
    )


def test_strategy_file_contents_match() -> None:
    """
    Reading the strategy file through either path yields identical bytes.
    Sanity guard against the symlink being wrong or a stale copy.
    """
    if not FREQ_DIR.is_symlink():
        pytest.skip("freqtrade strategies dir is not a symlink yet")
    core_bytes = CORE_FILE.read_bytes()
    link_bytes = FREQ_FILE.read_bytes()
    assert core_bytes == link_bytes, (
        f"strategy file content diverged: "
        f"core={len(core_bytes)}B link={len(link_bytes)}B"
    )


def test_strategy_declares_trend_rsi_class() -> None:
    """
    The strategy file declares a ``TrendRSI`` class.

    We inspect the source rather than importing the module because
    importing would require the freqtrade package to be available in
    the test environment, which is the responsibility of the FT
    Strategy worker, not the parity test.
    """
    if not CORE_FILE.is_file():
        pytest.skip("strategy file not yet at app/strategies/")
    text = CORE_FILE.read_text(encoding="utf-8")
    pattern = re.compile(r"^class\s+TrendRSI\b", re.MULTILINE)
    assert pattern.search(text), (
        "TrendRSI class not declared in " + str(CORE_FILE)
    )
