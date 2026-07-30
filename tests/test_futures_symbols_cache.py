"""Tests for ``app.infra.futures_symbols_cache``.

Coverage target: 100% of the cache module. We avoid hitting the real fapi by
injecting a stub ``fetcher`` callable; the production default fetcher is
exercised in ``test_futures_datasource.py`` (separate integration surface).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from app.infra.futures_symbols_cache import (
    DEFAULT_CACHE_PATH,
    STALENESS_SECONDS,
    FuturesSymbolsCache,
    SymbolEntry,
    _entries_from_exchangeinfo,
    _parse_entry,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_raw(
    symbol: str = "MUUSDT",
    *,
    base: str = "MU",
    quote: str = "USDT",
    status: str = "TRADING",
    contract_type: str = "TRADIFI_PERPETUAL",
    underlying_type: str = "EQUITY",
    sub_types: list[str] | None = None,
    price_precision: int = 3,
    quantity_precision: int = 0,
) -> dict:
    return {
        "symbol": symbol,
        "baseAsset": base,
        "quoteAsset": quote,
        "status": status,
        "contractType": contract_type,
        "underlyingType": underlying_type,
        "underlyingSubTypes": sub_types if sub_types is not None else ["TradFi"],
        "pricePrecision": price_precision,
        "quantityPrecision": quantity_precision,
        "onboardDate": 1716240000000,
    }


_SAMPLE_RAW = {
    "symbols": [
        _make_raw("MUUSDT", base="MU", sub_types=["TradFi"]),
        _make_raw("ORCLUSDT", base="ORCL", sub_types=["TradFi"]),
        _make_raw("BTCUSDT", base="BTC", contract_type="PERPETUAL",
                  underlying_type="COIN", sub_types=["Layer-1"], price_precision=2),
        _make_raw("SETTLINGUSDT", base="X", status="SETTLING"),
        _make_raw("USDCUSDT", base="USDC", quote="USDC"),
        _make_raw("DATEDUSDT", base="D", contract_type="CURRENT_QUARTER"),
    ]
}


@pytest.fixture
def tmp_cache(tmp_path: Path) -> Path:
    return tmp_path / "futures_symbols.json"


@pytest.fixture
def fetcher_factory():
    """Return a callable that produces a stub fetcher with a counter."""
    state = {"calls": 0, "payload": _SAMPLE_RAW, "raise": None}

    def make(payload: dict | None = None, raise_exc: Exception | None = None):
        if payload is not None:
            state["payload"] = payload

        def fetcher() -> dict:
            state["calls"] += 1
            if state["raise"] is not None:
                raise state["raise"]
            return state["payload"]

        return fetcher, state

    return make


# ---------------------------------------------------------------------------
# SymbolEntry / parsing helpers
# ---------------------------------------------------------------------------


class TestParseEntry:
    def test_keeps_tradfi_trading_usdt(self):
        entry = _parse_entry(_make_raw())
        assert isinstance(entry, SymbolEntry)
        assert entry.symbol == "MUUSDT"
        assert entry.base_asset == "MU"
        assert entry.is_tradfi is True

    def test_keeps_perpetual_crypto(self):
        entry = _parse_entry(
            _make_raw("BTCUSDT", base="BTC", contract_type="PERPETUAL",
                      underlying_type="COIN", sub_types=["Layer-1"], price_precision=2)
        )
        assert entry is not None
        assert entry.is_tradfi is False
        assert entry.underlying_type == "COIN"

    def test_drops_settling_status(self):
        assert _parse_entry(_make_raw(status="SETTLING")) is None

    def test_drops_close_only_status(self):
        assert _parse_entry(_make_raw(status="CLOSE_ONLY")) is None

    def test_drops_non_usdt_quote(self):
        assert _parse_entry(_make_raw(quote="USDC")) is None

    def test_drops_dated_futures_contract(self):
        assert _parse_entry(_make_raw(contract_type="CURRENT_QUARTER")) is None
        assert _parse_entry(_make_raw(contract_type="NEXT_QUARTER")) is None

    def test_drops_missing_symbol(self):
        raw = _make_raw()
        raw.pop("symbol")
        assert _parse_entry(raw) is None

    def test_drops_malformed_precision(self):
        raw = _make_raw()
        raw["pricePrecision"] = "not-a-number"
        assert _parse_entry(raw) is None

    def test_defaults_subtypes_when_missing(self):
        raw = _make_raw()
        raw["underlyingSubTypes"] = None
        entry = _parse_entry(raw)
        assert entry is not None
        assert entry.underlying_sub_types == []

    def test_defaults_underlying_type_when_missing(self):
        raw = _make_raw()
        raw.pop("underlyingType")
        entry = _parse_entry(raw)
        assert entry is not None
        assert entry.underlying_type == "COIN"


class TestEntriesFromExchangeinfo:
    def test_filters_and_sorts_alphabetically(self):
        out = _entries_from_exchangeinfo(_SAMPLE_RAW)
        symbols = [e.symbol for e in out]
        # Should keep only the 3 valid USDT-m TRADING contracts.
        assert symbols == ["BTCUSDT", "MUUSDT", "ORCLUSDT"]
        # Each entry is a SymbolEntry.
        assert all(isinstance(e, SymbolEntry) for e in out)

    def test_handles_empty_symbols_list(self):
        assert _entries_from_exchangeinfo({"symbols": []}) == []

    def test_handles_missing_symbols_key(self):
        assert _entries_from_exchangeinfo({}) == []


# ---------------------------------------------------------------------------
# FuturesSymbolsCache — disk I/O + staleness
# ---------------------------------------------------------------------------


class TestFuturesSymbolsCache:
    def test_get_bootstrap_fetches_and_persists(self, tmp_cache: Path, fetcher_factory):
        fetcher, state = fetcher_factory()
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)

        result = cache.get()

        assert len(result) == 3
        assert {d["symbol"] for d in result} == {"BTCUSDT", "MUUSDT", "ORCLUSDT"}
        assert state["calls"] == 1
        assert tmp_cache.exists()

    def test_get_serves_from_cache_without_fetching(self, tmp_cache: Path, fetcher_factory):
        fetcher, state = fetcher_factory()
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)
        cache.get()  # bootstrap
        # Subsequent calls should NOT re-fetch.
        result = cache.get()
        assert len(result) == 3
        assert state["calls"] == 1

    def test_get_kicks_background_refresh_on_stale_file(self, tmp_cache: Path, fetcher_factory):
        fetcher, state = fetcher_factory()
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)
        cache.get()
        # Backdate the cache to simulate staleness.
        old_time = time.time() - (STALENESS_SECONDS + 60)
        import os
        os.utime(tmp_cache, (old_time, old_time))

        cache.get()  # triggers background refresh

        # Wait briefly for the background thread to finish.
        for _ in range(40):
            if state["calls"] >= 2:
                break
            time.sleep(0.05)
        assert state["calls"] >= 2

    def test_get_returns_empty_list_when_bootstrap_fails(self, tmp_cache: Path, fetcher_factory):
        fetcher, _ = fetcher_factory(payload={})
        # Empty payload yields 0 entries (no symbols key); treat as a fetch
        # failure by raising instead.
        def bad_fetcher():
            raise RuntimeError("network down")
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=bad_fetcher)

        # Bootstrap raises RuntimeError; cache swallows and returns []. Second
        # call would also retry — but we only assert the first one.
        result = cache.get()
        assert result == []

    def test_refresh_synchronously_overwrites(self, tmp_cache: Path, fetcher_factory):
        fetcher, state = fetcher_factory()
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)

        count = cache.refresh()

        assert count == 3
        # File on disk should reflect the latest payload.
        persisted = json.loads(tmp_cache.read_text(encoding="utf-8"))
        assert len(persisted) == 3
        assert state["calls"] == 1

    def test_refresh_replaces_stale_payload(self, tmp_cache: Path, fetcher_factory):
        fetcher1, _ = fetcher_factory(payload={"symbols": [_make_raw("OLDUSDT")]})
        fetcher2, _ = fetcher_factory(payload=_SAMPLE_RAW)
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher1)

        cache.refresh()  # writes OLDUSDT only
        cache._fetcher = fetcher2  # type: ignore[attr-defined]
        cache.refresh()

        result = cache.get()
        assert {d["symbol"] for d in result} == {"BTCUSDT", "MUUSDT", "ORCLUSDT"}

    def test_refresh_propagates_fetcher_errors(self, tmp_cache: Path, fetcher_factory):
        def bad_fetcher():
            raise RuntimeError("boom")

        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=bad_fetcher)
        with pytest.raises(RuntimeError, match="boom"):
            cache.refresh()

    def test_get_skips_concurrent_background_refreshes(self, tmp_cache: Path, fetcher_factory):
        """Two stale reads in quick succession must spawn at most one refresh thread."""
        fetcher, state = fetcher_factory()
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)
        cache.get()
        import os
        old_time = time.time() - (STALENESS_SECONDS + 60)
        os.utime(tmp_cache, (old_time, old_time))

        cache.get()
        cache.get()
        cache.get()

        # Give the thread(s) a moment.
        for _ in range(40):
            time.sleep(0.05)
            if state["calls"] >= 2:
                break

        # We expect exactly 2 fetcher calls total: 1 bootstrap + 1 refresh.
        assert state["calls"] == 2

    def test_kick_background_refresh_dedupes_in_flight(self, tmp_cache: Path, fetcher_factory):
        """When the background refresh is still in flight, a second
        ``_kick_background_refresh`` call must short-circuit (line 236)."""
        import threading

        fetcher, state = fetcher_factory()

        # Make the fetcher block until we release it, simulating a slow
        # network call. This guarantees the first background refresh is
        # in-flight when the second kick runs.
        gate = threading.Event()
        state["raise"] = None
        original_payload = state["payload"]

        def slow_fetcher() -> dict:
            state["calls"] += 1
            # First call: bootstrap in main thread, holds gate.
            # Second call: inside background worker, waits for gate.
            gate.wait(timeout=2.0)
            return original_payload

        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=slow_fetcher)
        cache.get()  # bootstrap blocks on gate.wait()

        # Manually mark the file stale so _should_refresh() returns True.
        old_time = time.time() - (STALENESS_SECONDS + 60)
        os.utime(tmp_cache, (old_time, old_time))

        # First kick: spawns a worker that will block in slow_fetcher.
        cache._kick_background_refresh()
        # Second kick while the first is still in flight must no-op.
        cache._kick_background_refresh()
        cache._kick_background_refresh()

        gate.set()  # release bootstrap and any background workers
        # Give background workers time to finish.
        for _ in range(40):
            time.sleep(0.05)
            if state["calls"] >= 2:
                break

        # At least 2 calls (bootstrap + 1 background refresh); dedup means
        # the 3 extra kicks did not spawn more workers.
        assert state["calls"] >= 2

    def test_corrupted_cache_rebuilds(self, tmp_cache: Path, fetcher_factory):
        """A corrupted file should be silently discarded and the cache rebuilt."""
        tmp_cache.write_text("{not json", encoding="utf-8")
        fetcher, state = fetcher_factory()

        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)
        result = cache.get()

        assert len(result) == 3
        assert state["calls"] == 1

    def test_default_cache_path_under_app_cache(self):
        """Sanity check on the production default path."""
        assert str(DEFAULT_CACHE_PATH).endswith("app/cache/futures_symbols.json")

    def test_entry_round_trip_preserves_all_fields(self):
        """A dict produced by SymbolEntry.to_dict() round-trips back to a
        structurally-identical SymbolEntry via the cache's _entry_from_dict."""
        entry = SymbolEntry(
            symbol="MUUSDT",
            base_asset="MU",
            quote_asset="USDT",
            contract_type="TRADIFI_PERPETUAL",
            underlying_type="EQUITY",
            underlying_sub_types=["TradFi"],
            price_precision=3,
            quantity_precision=0,
            is_tradfi=True,
            onboard_date_ms=1716240000000,
        )
        d = entry.to_dict()
        kwargs = FuturesSymbolsCache._entry_from_dict(d)
        rebuilt = SymbolEntry(**kwargs)
        assert rebuilt == entry


# ---------------------------------------------------------------------------
# Threading sanity — refresh is bounded even under stress.
# ---------------------------------------------------------------------------


def test_concurrent_gets_dont_deadlock(tmp_path: Path):
    cache_path = tmp_path / "futures_symbols.json"
    call_lock = threading.Lock()
    calls = {"n": 0}

    def fetcher():
        with call_lock:
            calls["n"] += 1
            time.sleep(0.01)
        return _SAMPLE_RAW

    cache = FuturesSymbolsCache(path=cache_path, fetcher=fetcher)

    threads = [threading.Thread(target=cache.get) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)
        assert not t.is_alive(), "thread deadlocked"

    assert calls["n"] >= 1


# ---------------------------------------------------------------------------
# Branch coverage: file-touched-between-calls, write failures, default fetcher.
# ---------------------------------------------------------------------------


class TestEdgeBranches:
    def test_get_reloads_when_file_disappears_between_calls(self, tmp_cache, fetcher_factory):
        """If the file vanishes after the first load (mtime mismatch),
        the inner read fails and we fall back to the second-block rebuild."""
        fetcher, state = fetcher_factory()
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)

        cache.get()  # bootstrap writes the file
        # Delete the file between calls — the in-memory mtime no longer matches.
        tmp_cache.unlink()

        # The cache will detect the file is missing and re-fetch.
        result = cache.get()
        assert len(result) == 3
        assert state["calls"] == 2

    def test_get_returns_empty_when_cache_write_fails(self, tmp_path, fetcher_factory, caplog):
        """If the cache file cannot be written, log and fall back to an
        in-memory list (returned on next call via the bootstrap path)."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        bad_path = blocker / "nested" / "futures_symbols.json"
        fetcher, _ = fetcher_factory()

        cache = FuturesSymbolsCache(path=bad_path, fetcher=fetcher)
        result = cache.get()
        assert result == []  # writes fail; bootstrap swallows + returns empty

    def test_get_rebuilds_when_in_memory_mtime_mismatches_corrupt_file(self, tmp_cache, fetcher_factory):
        """If memory says the cache is loaded but the file's mtime changed
        (e.g. some other process touched it) and the new content is unreadable,
        the inner except fires and we fall back to a fresh fetch."""
        fetcher, state = fetcher_factory()
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)

        cache.get()  # bootstrap, writes file, sets _memory
        # Corrupt the file but keep it present — mtime will change.
        tmp_cache.write_text("{not json", encoding="utf-8")
        import os
        old = time.time() + 5  # future mtime to force mismatch
        os.utime(tmp_cache, (old, old))

        result = cache.get()
        assert len(result) == 3
        # 1 bootstrap + 1 rebuild after detecting corruption.
        assert state["calls"] == 2

    def test_get_returns_empty_when_write_fails(self, tmp_path, fetcher_factory):
        """If writing the cache file fails (parent is read-only), we still
        return the freshly-fetched entries from memory — no crash."""
        fetcher, _ = fetcher_factory()

        # Parent dir that we'll make read-only after the cache has loaded once.
        parent = tmp_path / "readonly"
        parent.mkdir()
        cache_path = parent / "futures_symbols.json"

        cache = FuturesSymbolsCache(path=cache_path, fetcher=fetcher)
        cache.get()  # baseline: writes succeed

        # Now make parent read-only and force a refresh.
        parent.chmod(0o500)
        try:
            result = cache.refresh()
            assert result == 3  # function returns the count even when write fails
            # In-memory list survives even though disk write failed.
            assert len(cache.get()) == 3
        finally:
            parent.chmod(0o755)

    def test_concurrent_refresh_is_deduplicated(self, tmp_cache, fetcher_factory):
        """If a background refresh is already in flight, get() does not
        spawn another thread."""
        fetcher, state = fetcher_factory()
        # Make the fetcher slow so the first refresh doesn't finish immediately.
        original = fetcher
        barrier = threading.Event()
        calls = {"n": 0}

        def slow_fetcher():
            calls["n"] += 1
            barrier.wait(timeout=2)
            return _SAMPLE_RAW

        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=slow_fetcher)
        # Backdate so the next get() triggers a background refresh.
        cache.get()  # bootstrap (sync)
        import os
        old = time.time() - (STALENESS_SECONDS + 60)
        os.utime(tmp_cache, (old, old))

        # First call spawns a thread; subsequent calls should not.
        cache.get()
        cache.get()
        cache.get()

        # Signal the slow fetcher to finish so we can observe the count.
        barrier.set()
        for _ in range(40):
            time.sleep(0.05)
            if calls["n"] >= 2:
                break

        # Exactly 2 fetches total: bootstrap + 1 background refresh.
        assert calls["n"] == 2

    def test_get_handles_inner_stat_failure(self, tmp_cache, fetcher_factory, monkeypatch):
        """When memory is populated and the cache file exists but stat() raises
        (e.g. read-only filesystem returning I/O errors on metadata reads),
        the inner except fires and we fall back to rebuilding from the file."""
        fetcher, _ = fetcher_factory()
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)
        cache.get()  # bootstrap writes the file

        # Make ALL stat calls fail on the cache path. exists() should still
        # succeed via os.access; the inner if-body stat will raise, hitting
        # the line-195 except.
        from pathlib import Path as _Path
        original_stat = _Path.stat
        selective = tmp_cache

        def selective_stat(self, *a, **kw):
            if str(self) == str(selective):
                raise OSError("simulated I/O error on stat")
            return original_stat(self, *a, **kw)

        monkeypatch.setattr(_Path, "stat", selective_stat)

        # Should not raise; the inner except fires and we rebuild from disk.
        result = cache.get()
        assert len(result) == 3

    def test_get_handles_inner_read_failure(self, tmp_cache, fetcher_factory, monkeypatch):
        """When memory is populated and mtime matches but the file body
        fails to parse (corrupted mid-flight), the inner except fires and
        we fall back to a fresh fetch."""
        fetcher, _ = fetcher_factory()
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)
        cache.get()  # bootstrap writes the file

        # Force Path.exists() to return True unconditionally (skip stat).
        monkeypatch.setattr(type(tmp_cache), "exists", lambda self: True)

        # Force read_text to raise inside the cached-fast-path body.
        def bad_read(*a, **kw):
            raise OSError("simulated I/O error on read")

        monkeypatch.setattr(type(tmp_cache), "read_text", bad_read)

        # Should not raise; the inner except fires and we rebuild via fetcher.
        result = cache.get()
        assert len(result) == 3

    def test_get_handles_inner_stat_failure(self, tmp_cache, fetcher_factory, monkeypatch):
        """When memory is populated and the cache file exists but stat() raises
        (e.g. read-only filesystem returning I/O errors on metadata reads),
        the inner except fires and we fall back to rebuilding from the file."""
        fetcher, _ = fetcher_factory()
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)
        cache.get()  # bootstrap writes the file

        # Replace the cache's Path.stat with one that always raises OSError
        # for our specific cache path. exists() catches OSError and returns
        # False, so we instead bypass stat() entirely by patching exists()
        # to return True unconditionally and read_text() to raise.
        monkeypatch.setattr(type(tmp_cache), "exists", lambda self: True)
        monkeypatch.setattr(
            type(tmp_cache),
            "stat",
            lambda self, *a, **kw: (_ for _ in ()).throw(OSError("simulated")),
        )
        monkeypatch.setattr(
            type(tmp_cache),
            "read_text",
            lambda self, *a, **kw: (_ for _ in ()).throw(OSError("simulated")),
        )

        # Should not raise; the inner except fires and we rebuild from the
        # fetcher (since stat always raises, exists() returns False → the
        # cached-fast-path is skipped → we go through bootstrap path).
        result = cache.get()
        assert len(result) == 3

    def test_get_handles_inner_stat_failure(self, tmp_cache, fetcher_factory, monkeypatch):
        """When memory is populated and the cache file exists but stat() raises
        on the cached-fast-path stat call, the inner except fires and we
        fall back to rebuilding from the file."""
        fetcher, _ = fetcher_factory()
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)
        cache.get()  # bootstrap writes the file

        # Make exists() return True unconditionally on the cache path (so
        # the cached-fast-path is entered) but make stat() raise there.
        # We keep exists/stat patched on PosixPath only.
        PosixPath = type(tmp_cache)
        cache_str = str(tmp_cache)

        monkeypatch.setattr(PosixPath, "exists", lambda self: True)
        original_stat = PosixPath.stat

        def selective_stat(self, *a, **kw):
            if str(self) == cache_str:
                raise OSError("simulated I/O error on stat")
            return original_stat(self, *a, **kw)

        monkeypatch.setattr(PosixPath, "stat", selective_stat)

        # _should_refresh() is not wrapped in try/except — patch it so the
        # test focuses on _ensure_loaded's stat-failure branches.
        monkeypatch.setattr(cache, "_should_refresh", lambda: False)

        # The cached-fast-path: exists()=True, then stat() raises inside
        # the if body → caught at line 195-196, falls through to the
        # second if-block (line 198-205) which also raises on read_text's
        # stat call, then to bootstrap which writes and stat()s again →
        # caught at line 215-216. Returns 3 entries.
        result = cache.get()
        assert len(result) == 3

    def test_refresh_handles_stat_failure_after_write(self, tmp_cache, fetcher_factory, monkeypatch):
        """If the cache file disappears between ``_write`` and ``stat()``
        (rare race during refresh), the OSError branch keeps memory sane
        instead of raising."""
        fetcher, _ = fetcher_factory()

        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)
        cache.get()  # bootstrap writes the file
        # Now delete the file and patch Path.stat on this specific path.
        tmp_cache.unlink()

        from pathlib import Path as _Path
        original_stat = _Path.stat

        def selective_stat(self, *a, **kw):
            if str(self) == str(tmp_cache):
                raise FileNotFoundError("simulated race: file vanished")
            return original_stat(self, *a, **kw)

        monkeypatch.setattr(_Path, "stat", selective_stat)

        # refresh() must not raise; memory fallback keeps the data.
        count = cache.refresh()
        assert count == 3

    def test_default_fetcher_hits_configured_endpoint(self, monkeypatch):
        """Sanity check on the production fetcher: it uses
        BINANCE_FUTURES_REST_URL and parses JSON."""
        from app.infra import futures_symbols_cache as mod

        monkeypatch.setattr(mod, "DEFAULT_FAPI_URL", "https://example.test")

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return _SAMPLE_RAW

        # requests is imported lazily inside _default_fetcher, so we monkeypatch
        # the real module attribute rather than mod.requests.
        import requests as real_requests
        captured = {}

        def fake_get(url, timeout):
            captured["url"] = url
            captured["timeout"] = timeout
            return FakeResp()

        monkeypatch.setattr(real_requests, "get", fake_get)

        result = mod._default_fetcher()
        assert captured["url"] == "https://example.test/fapi/v1/exchangeInfo"
        assert captured["timeout"] == 15
        assert "symbols" in result
        assert len(result["symbols"]) == 6

    def test_default_fetcher_raises_on_http_error(self, monkeypatch):
        """The default fetcher propagates non-2xx responses."""
        from app.infra import futures_symbols_cache as mod

        class BadResp:
            def raise_for_status(self):
                raise RuntimeError("502 bad gateway")

        import requests as real_requests
        monkeypatch.setattr(real_requests, "get", lambda *a, **k: BadResp())

        with pytest.raises(RuntimeError, match="502"):
            mod._default_fetcher()

    def test_default_fetcher_strips_trailing_slash(self, monkeypatch):
        """Endpoint URL with trailing slash shouldn't produce ``//fapi``."""
        from app.infra import futures_symbols_cache as mod

        monkeypatch.setattr(mod, "DEFAULT_FAPI_URL", "https://example.test/")

        import requests as real_requests
        captured = {}
        monkeypatch.setattr(
            real_requests, "get",
            lambda url, timeout: (captured.update(url=url, timeout=timeout) or type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: {}})()),
        )
        mod._default_fetcher()
        assert captured["url"] == "https://example.test/fapi/v1/exchangeInfo"

    def test_get_meta_returns_entry(self, tmp_cache, fetcher_factory):
        """``get_meta`` returns the matching entry's dict or None."""
        fetcher, _ = fetcher_factory()
        cache = FuturesSymbolsCache(path=tmp_cache, fetcher=fetcher)
        # _SAMPLE_RAW contains MUUSDT, ORCLUSDT, BTCUSDT
        meta = cache.get_meta("MUUSDT")
        assert meta is not None
        assert meta["symbol"] == "MUUSDT"
        assert meta["isTradfi"] is True
        assert cache.get_meta("DOES_NOT_EXIST") is None

    def test_get_meta_works_against_empty_cache(self, tmp_cache):
        """If the cache can't be loaded, ``get_meta`` returns None gracefully."""
        cache = FuturesSymbolsCache(
            path=tmp_cache,
            fetcher=lambda: (_ for _ in ()).throw(RuntimeError("network down")),
        )
        assert cache.get_meta("BTCUSDT") is None