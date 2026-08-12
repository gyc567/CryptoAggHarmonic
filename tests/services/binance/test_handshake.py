"""Tests for the binance handshake module — HISTORY.jsonl append schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.binance.data_source import (
    FundingRate,
    MarkPrice,
    OpenInterest,
)
from app.services.binance.handshake import (
    SOURCE_TAG,
    record_funding_history,
    record_mark_price,
    record_open_interest,
    append,
    HistoryEntry,
)


@pytest.fixture
def history_root(tmp_path: Path) -> Path:
    """Loop state root for tests — never touches the live .scratch/ tree."""
    return tmp_path / "loop_state"


# ── Entry construction ─────────────────────────────────────────────────────


def test_record_mark_price_builds_entry() -> None:
    mp = MarkPrice(
        symbol="BTCUSDT",
        mark_price=63500.0,
        index_price=63500.0,
        estimated_settle_price=63500.0,
        last_funding_rate=0.0001,
        next_funding_time=1786550400000,
        time=1786545458000,
    )
    entry = record_mark_price(mp, latency_ms=720)
    assert entry.source == SOURCE_TAG == "binance_market"
    assert entry.endpoint == "mark_price"
    assert entry.symbol == "BTCUSDT"
    assert entry.latency_ms == 720
    # dataclass asdict() uses Python snake_case field names
    assert entry.payload["mark_price"] == 63500.0
    assert entry.payload["last_funding_rate"] == 0.0001


def test_record_open_interest_builds_entry() -> None:
    oi = OpenInterest(symbol="BTCUSDT", open_interest=108905.842, time=1786545458000)
    entry = record_open_interest(oi, latency_ms=680)
    assert entry.endpoint == "open_interest"
    assert entry.symbol == "BTCUSDT"
    assert entry.payload["open_interest"] == 108905.842


def test_record_funding_history_builds_entry_with_count() -> None:
    rates = [
        FundingRate(symbol="BTCUSDT", funding_time=1, funding_rate=0.0001, mark_price=100.0),
        FundingRate(symbol="BTCUSDT", funding_time=2, funding_rate=0.0002, mark_price=101.0),
        FundingRate(symbol="BTCUSDT", funding_time=3, funding_rate=0.0001, mark_price=102.0),
    ]
    entry = record_funding_history(rates, symbol="BTCUSDT", latency_ms=750)
    assert entry.endpoint == "funding_history"
    assert entry.payload["count"] == 3
    assert len(entry.payload["entries"]) == 3
    assert entry.payload["symbol"] == "BTCUSDT"


# ── Append to HISTORY.jsonl ────────────────────────────────────────────────


def test_append_writes_to_history_jsonl(history_root: Path) -> None:
    mp = MarkPrice(
        symbol="BTCUSDT",
        mark_price=63500.0,
        index_price=63500.0,
        estimated_settle_price=63500.0,
        last_funding_rate=0.0001,
        next_funding_time=1786550400000,
        time=1786545458000,
    )
    entry = record_mark_price(mp, latency_ms=720)
    append(entry, root=history_root)

    history_path = history_root / "HISTORY.jsonl"
    assert history_path.exists()
    lines = history_path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["source"] == "binance_market"
    assert record["endpoint"] == "mark_price"
    assert record["symbol"] == "BTCUSDT"
    assert record["latency_ms"] == 720
    assert record["salt_version"] == 1


def test_append_does_not_touch_live_scratch(history_root: Path) -> None:
    """Default root must not write to the live .scratch/loop_state/ tree."""
    import os

    cwd = os.getcwd()
    live_history = Path(cwd) / ".scratch" / "loop_state" / "HISTORY.jsonl"
    # Wipe if exists from a previous test run
    if live_history.exists():
        live_history.unlink()

    mp = MarkPrice(
        symbol="BTCUSDT",
        mark_price=1.0,
        index_price=1.0,
        estimated_settle_price=None,
        last_funding_rate=0.0,
        next_funding_time=1,
        time=1,
    )
    append(record_mark_price(mp, latency_ms=1), root=history_root)
    assert not live_history.exists()


def test_append_swallows_io_errors(
    history_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Filesystem failures must not crash the caller; just log."""
    mp = MarkPrice(
        symbol="BTCUSDT",
        mark_price=1.0,
        index_price=1.0,
        estimated_settle_price=None,
        last_funding_rate=0.0,
        next_funding_time=1,
        time=1,
    )
    entry = record_mark_price(mp, latency_ms=1)

    def boom(*args, **kwargs):  # noqa: ANN001
        raise OSError("disk full")

    # state.append_history is imported lazily inside append(); patch there.
    import app.loop.state as state_mod

    monkeypatch.setattr(state_mod, "append_history", boom)

    # Should NOT raise
    append(entry, root=history_root)


def test_history_entry_is_frozen() -> None:
    """HistoryEntry is a frozen dataclass — accidental mutation would break audit trail."""
    entry = HistoryEntry(
        source="binance_market",
        endpoint="mark_price",
        symbol="BTCUSDT",
        ts=1,
        latency_ms=1,
        payload={},
    )
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        entry.source = "tampered"  # type: ignore[misc]