"""Tests for the binance metrics registry."""

from __future__ import annotations

import pytest

from app.services.binance.metrics import get_snapshot, record_fetch, reset


def test_record_then_snapshot() -> None:
    reset()
    record_fetch("mark_price", "ok", 0.42)
    record_fetch("mark_price", "ok", 0.55)
    record_fetch("open_interest", "timeout", 5.0)

    snap = get_snapshot()
    counter = snap["counter"]
    assert counter[("mark_price", "ok")] == 2
    assert counter[("open_interest", "timeout")] == 1
    # Histogram: mark_price bucket le=1.0 should have 2 observations
    hist = snap["histogram"]
    assert "mark_price" in hist
    assert "open_interest" in hist
    # bucket count for le=1.0 is index 4 (0.05, 0.1, 0.25, 0.5, 1.0)
    mark_buckets = hist["mark_price"]
    assert mark_buckets[-2] == 2     # count
    assert mark_buckets[-1] == pytest.approx(0.97, abs=1e-6)  # sum


def test_reset_clears_state() -> None:
    record_fetch("mark_price", "ok", 0.1)
    reset()
    snap = get_snapshot()
    assert snap["counter"] == {}
    assert snap["histogram"] == {}


def test_unknown_endpoint_creates_histogram_entry() -> None:
    reset()
    record_fetch("totally_new_endpoint", "ok", 0.2)
    snap = get_snapshot()
    assert ("totally_new_endpoint", "ok") in snap["counter"]
    assert "totally_new_endpoint" in snap["histogram"]


def test_snapshot_buckets_match_schema() -> None:
    """Bucket boundaries match the LOOP.md §7.2 scheme."""
    snap = get_snapshot()
    expected = [0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
    assert snap["histogram_buckets_s"] == expected