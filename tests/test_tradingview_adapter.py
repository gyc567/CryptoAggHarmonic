"""Unit tests for the TradingView bridge health cache.

These cover the 5-second sliding-window cache on
``tradingview_adapter.is_bridge_healthy``. The probe itself is delegated
to ``_probe_bridge_health`` so tests can patch it without standing up a
real HTTP server.
"""
from __future__ import annotations

from unittest import mock

import pytest

from app.infra import tradingview_adapter as adapter


@pytest.fixture(autouse=True)
def _reset_cache():
    """Ensure cache state doesn't leak between tests."""
    adapter.reset_health_cache()
    yield
    adapter.reset_health_cache()


def test_first_call_probes_bridge_and_caches_true(monkeypatch):
    monkeypatch.setattr(adapter, "HEALTH_CACHE_TTL", 5.0)
    monkeypatch.setattr(
        adapter, "_probe_bridge_health", lambda: True,
    )
    assert adapter.is_bridge_healthy() is True

    # A second probe inside the TTL should not be called again.
    with mock.patch.object(
        adapter, "_probe_bridge_health", side_effect=AssertionError("called"),
    ):
        assert adapter.is_bridge_healthy() is True


def test_probe_failure_caches_false_until_ttl_expires(monkeypatch):
    monkeypatch.setattr(adapter, "HEALTH_CACHE_TTL", 5.0)
    monkeypatch.setattr(
        adapter, "_probe_bridge_health", lambda: False,
    )
    assert adapter.is_bridge_healthy() is False

    # Flip the underlying truth; the stale cache still wins.
    monkeypatch.setattr(
        adapter, "_probe_bridge_health", lambda: True,
    )
    with mock.patch.object(
        adapter, "_probe_bridge_health", side_effect=AssertionError("called"),
    ):
        assert adapter.is_bridge_healthy() is False


def test_cache_reprobes_after_ttl_expires(monkeypatch):
    monkeypatch.setattr(adapter, "HEALTH_CACHE_TTL", 5.0)
    calls = {"n": 0}

    def fake_probe():
        calls["n"] += 1
        return True

    monkeypatch.setattr(adapter, "_probe_bridge_health", fake_probe)
    assert adapter.is_bridge_healthy() is True
    assert calls["n"] == 1

    # Force expiry by rewinding the timestamp.
    with adapter._health_lock:
        adapter._health_cache["expires_at"] = 0.0
    assert adapter.is_bridge_healthy() is True
    assert calls["n"] == 2


def test_reset_health_cache_forces_immediate_reprobe(monkeypatch):
    monkeypatch.setattr(adapter, "HEALTH_CACHE_TTL", 5.0)
    calls = {"n": 0}

    def fake_probe():
        calls["n"] += 1
        return True

    monkeypatch.setattr(adapter, "_probe_bridge_health", fake_probe)

    assert adapter.is_bridge_healthy() is True
    assert calls["n"] == 1

    adapter.reset_health_cache()
    assert adapter.is_bridge_healthy() is True
    assert calls["n"] == 2


def test_concurrent_calls_only_probe_once(monkeypatch):
    """Even under concurrent expiry, only one probe should run per TTL."""
    import threading

    monkeypatch.setattr(adapter, "HEALTH_CACHE_TTL", 5.0)
    in_flight = threading.Event()
    proceed = threading.Event()
    calls = {"n": 0}

    def slow_probe():
        calls["n"] += 1
        in_flight.set()
        proceed.wait(timeout=1.0)
        return True

    monkeypatch.setattr(adapter, "_probe_bridge_health", slow_probe)

    results = []
    barrier = threading.Barrier(3)

    def worker():
        barrier.wait()
        results.append(adapter.is_bridge_healthy())

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    in_flight.wait(timeout=1.0)
    proceed.set()
    for t in threads:
        t.join(timeout=2.0)

    assert all(r is True for r in results)
    # First call probes; the other two see the fresh result in the cache.
    assert calls["n"] == 1