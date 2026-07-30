"""Tests for the watchlist HTTP routes (``app.api.watchlist_routes``).

Strategy: a stub cache + stub store injected via monkeypatch so the
routes are exercised end-to-end against the Flask test client. No Supabase,
no network, no on-disk cache file.

Coverage target: 100 percent of ``app/api/watchlist_routes.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.api import watchlist_routes
from app.api.auth import LOCAL_DEV_USER
from app.domain.enums import ErrorCode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_SAMPLE_RAW = {
    "symbols": [
        {
            "symbol": "MUUSDT",
            "baseAsset": "MU",
            "quoteAsset": "USDT",
            "contractType": "TRADIFI_PERPETUAL",
            "underlyingType": "EQUITY",
            "underlyingSubTypes": ["TradFi"],
            "pricePrecision": 3,
            "quantityPrecision": 0,
            "status": "TRADING",
            "isTradfi": True,
        },
        {
            "symbol": "ORCLUSDT",
            "baseAsset": "ORCL",
            "quoteAsset": "USDT",
            "contractType": "TRADIFI_PERPETUAL",
            "underlyingType": "EQUITY",
            "underlyingSubTypes": ["TradFi"],
            "pricePrecision": 3,
            "quantityPrecision": 0,
            "status": "TRADING",
            "isTradfi": True,
        },
        {
            "symbol": "BTCUSDT",
            "baseAsset": "BTC",
            "quoteAsset": "USDT",
            "contractType": "PERPETUAL",
            "underlyingType": "COIN",
            "underlyingSubTypes": ["Layer-1"],
            "pricePrecision": 2,
            "quantityPrecision": 3,
            "status": "TRADING",
            "isTradfi": False,
        },
    ]
}


class _StubCache:
    """Drop-in replacement for ``FuturesSymbolsCache`` with hard-coded data."""

    def __init__(self, entries: list[dict] | None = None, fail: bool = False):
        self._entries = entries if entries is not None else _SAMPLE_RAW["symbols"]
        self._fail = fail
        self.refresh_calls = 0

    def get(self) -> list[dict]:
        if self._fail:
            raise RuntimeError("cache down")
        return list(self._entries)

    def get_meta(self, symbol: str) -> dict | None:
        if self._fail:
            raise RuntimeError("cache down")
        for entry in self._entries:
            if entry.get("symbol") == symbol:
                return entry
        return None

    def refresh(self) -> int:
        self.refresh_calls += 1
        if self._fail:
            raise RuntimeError("cache down")
        return len(self._entries)


@pytest.fixture
def stub_cache() -> _StubCache:
    return _StubCache()


@pytest.fixture
def stub_store():
    """In-memory store with the stub cache as its whitelist resolver."""
    from app.infra.watchlist_store import (
        SymbolMeta,
        WatchlistStore,
        symbol_meta_from_cache,
    )

    cache = _StubCache()

    def resolve(symbol: str):
        entry = cache.get_meta(symbol)
        return symbol_meta_from_cache(entry) if entry else None

    store = WatchlistStore(whitelist_resolver=resolve)
    store._client = None  # force memory
    return store


@pytest.fixture(autouse=True)
def _enable_disable_auth(monkeypatch):
    """require_auth bypasses token check when DISABLE_AUTH=1."""
    monkeypatch.setenv("DISABLE_AUTH", "1")


@pytest.fixture
def client(stub_cache, stub_store, monkeypatch):
    """Flask test client with stubs wired in."""
    from app.main import app

    monkeypatch.setattr(watchlist_routes, "get_symbols_cache", lambda: stub_cache)
    monkeypatch.setattr(watchlist_routes, "_store", lambda: stub_store)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    # Reset module-level singleton so test ordering doesn't leak.
    from app.infra.futures_symbols_cache import reset_symbols_cache_for_tests
    reset_symbols_cache_for_tests()


# ---------------------------------------------------------------------------
# /api/markets/futures/symbols
# ---------------------------------------------------------------------------


class TestListFuturesSymbols:
    def test_returns_all_symbols(self, client):
        resp = client.get("/api/markets/futures/symbols")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["data"]["count"] == 3
        symbols = {e["symbol"] for e in body["data"]["results"]}
        assert symbols == {"MUUSDT", "ORCLUSDT", "BTCUSDT"}

    def test_q_filter_matches_symbol(self, client):
        resp = client.get("/api/markets/futures/symbols?q=MU")
        body = resp.get_json()
        # MUUSDT symbol contains MU; BTCUSDT contains MU... actually no.
        # MUUSDT matches, ORCL no, BTC no. But also baseAsset for MUUSDT is MU.
        assert resp.status_code == 200
        names = [e["symbol"] for e in body["data"]["results"]]
        assert "MUUSDT" in names

    def test_q_filter_is_case_insensitive(self, client):
        resp = client.get("/api/markets/futures/symbols?q=mu")
        body = resp.get_json()
        names = [e["symbol"] for e in body["data"]["results"]]
        assert "MUUSDT" in names

    def test_q_filter_matches_base_asset(self, client):
        resp = client.get("/api/markets/futures/symbols?q=ORCL")
        names = [e["symbol"] for e in resp.get_json()["data"]["results"]]
        assert "ORCLUSDT" in names

    def test_cache_failure_returns_500(self, client, stub_cache):
        stub_cache._fail = True
        resp = client.get("/api/markets/futures/symbols")
        assert resp.status_code == 500
        assert resp.get_json()["error"]["code"] == ErrorCode.INTERNAL_ERROR.value


# ---------------------------------------------------------------------------
# /api/admin/markets/futures/refresh
# ---------------------------------------------------------------------------


class TestRefreshCache:
    def test_local_dev_refresh_succeeds(self, client, stub_cache):
        resp = client.post(
            "/api/admin/markets/futures/refresh",
            json={"force": True},
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["count"] == 3
        assert stub_cache.refresh_calls == 1

    def test_refresh_with_empty_body(self, client, stub_cache):
        resp = client.post("/api/admin/markets/futures/refresh", json={})
        assert resp.status_code == 200
        assert stub_cache.refresh_calls == 1

    def test_refresh_validation_error(self, client):
        resp = client.post(
            "/api/admin/markets/futures/refresh",
            json={"force": "not-a-bool"},
        )
        assert resp.status_code == 422

    def test_refresh_failure_returns_500(self, client, stub_cache):
        stub_cache._fail = True
        resp = client.post("/api/admin/markets/futures/refresh", json={})
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /api/watchlist — list / add
# ---------------------------------------------------------------------------


class TestListWatchlist:
    def test_empty(self, client):
        resp = client.get("/api/watchlist")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["data"]["items"] == []
        assert body["data"]["limit"] == 50


class TestAddWatchlist:
    def test_add_success(self, client):
        resp = client.post(
            "/api/watchlist",
            json={"symbol": "MUUSDT", "note": "chip play"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        item = body["data"]["item"]
        assert item["symbol"] == "MUUSDT"
        assert item["note"] == "chip play"
        assert item["is_tradfi"] is True

    def test_add_without_note(self, client):
        resp = client.post("/api/watchlist", json={"symbol": "BTCUSDT"})
        assert resp.status_code == 200
        assert resp.get_json()["data"]["item"]["note"] == ""

    def test_add_unknown_symbol(self, client):
        resp = client.post("/api/watchlist", json={"symbol": "FOOUSDT"})
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == ErrorCode.INVALID_PARAMS.value

    def test_add_lowercase_symbol_rejected_by_schema(self, client):
        resp = client.post("/api/watchlist", json={"symbol": "muusdt"})
        assert resp.status_code == 422

    def test_add_oversized_note(self, client):
        resp = client.post(
            "/api/watchlist",
            json={"symbol": "MUUSDT", "note": "x" * 281},
        )
        assert resp.status_code == 422

    def test_add_missing_body(self, client):
        resp = client.post("/api/watchlist", data="not json", content_type="text/plain")
        # Empty/missing body becomes {} which fails Pydantic with 422.
        assert resp.status_code == 422

    def test_add_duplicate_returns_409(self, client):
        client.post("/api/watchlist", json={"symbol": "MUUSDT"})
        resp = client.post("/api/watchlist", json={"symbol": "MUUSDT"})
        assert resp.status_code == 409
        assert resp.get_json()["error"]["code"] == ErrorCode.DUPLICATE_SYMBOL.value

    def test_add_limit_reached(self, client, stub_cache, stub_store):
        # Fill the store to 50 via the store API directly (faster than
        # 50 HTTP calls) — the route layer just enforces what the store says.
        from app.infra.watchlist_store import (
            DuplicateError,
            LimitReachedError,
            SymbolMeta,
        )

        for i in range(50):
            entry = {
                "symbol": f"X{i:02d}USDT",
                "baseAsset": f"X{i:02d}",
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
                "underlyingType": "COIN",
                "underlyingSubTypes": [],
                "pricePrecision": 2,
                "quantityPrecision": 3,
                "status": "TRADING",
                "isTradfi": False,
            }
            stub_cache._entries.append(entry)
            stub_store.create_item(
                LOCAL_DEV_USER["id"],
                "futures",
                SymbolMeta(
                    symbol=entry["symbol"],
                    base_asset=entry["baseAsset"],
                    quote_asset="USDT",
                    contract_type="PERPETUAL",
                    underlying_type="COIN",
                    underlying_sub_types=[],
                    price_precision=2,
                    quantity_precision=3,
                    is_tradfi=False,
                ),
            )
        # 51st add via HTTP must hit LimitReachedError.
        resp = client.post(
            "/api/watchlist",
            json={"symbol": "ORCLUSDT"},  # ORCLUSDT not in stub yet
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == ErrorCode.WATCHLIST_LIMIT_REACHED.value

    def test_add_value_error_translates_422(self, client, stub_store, monkeypatch):
        """If the store raises ValueError (note too long slipped past the
        route's schema check), translate to 422."""
        from app.infra.watchlist_store import SymbolMeta as _SM  # noqa: F401
        original = stub_store.create_item

        def boom(*args, **kwargs):
            raise ValueError("synthetic too long")

        monkeypatch.setattr(stub_store, "create_item", boom)
        resp = client.post("/api/watchlist", json={"symbol": "MUUSDT", "note": "ok"})
        assert resp.status_code == 422
        monkeypatch.setattr(stub_store, "create_item", original)

    def test_add_unknown_symbol_error_translates(self, client, stub_store, monkeypatch):
        """If the store raises UnknownSymbolError (whitelist drift), the
        route maps it to 422 with the right code."""
        from app.infra.watchlist_store import UnknownSymbolError

        def boom(*args, **kwargs):
            raise UnknownSymbolError("MUUSDT")

        monkeypatch.setattr(stub_store, "create_item", boom)
        resp = client.post("/api/watchlist", json={"symbol": "MUUSDT"})
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == ErrorCode.WATCHLIST_UNKNOWN_SYMBOL.value

    def test_add_non_usdt_quote_rejected(self, client, stub_cache):
        """If the cache entry has quoteAsset != USDT, route rejects it."""
        stub_cache._entries.append({
            "symbol": "BTCUSDC",
            "baseAsset": "BTC",
            "quoteAsset": "USDC",
            "contractType": "PERPETUAL",
            "status": "TRADING",
        })
        resp = client.post("/api/watchlist", json={"symbol": "BTCUSDC"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /api/watchlist/<id> — update / delete
# ---------------------------------------------------------------------------


def _add_mu(client) -> str:
    resp = client.post("/api/watchlist", json={"symbol": "MUUSDT", "note": "n0"})
    return resp.get_json()["data"]["item"]["id"]


class TestUpdateWatchlist:
    def test_update_note(self, client):
        item_id = _add_mu(client)
        resp = client.patch(
            f"/api/watchlist/{item_id}",
            json={"note": "n1"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["item"]["note"] == "n1"

    def test_update_sort_index(self, client):
        item_id = _add_mu(client)
        resp = client.patch(
            f"/api/watchlist/{item_id}",
            json={"sort_index": 7},
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["item"]["sort_index"] == 7

    def test_update_both(self, client):
        item_id = _add_mu(client)
        resp = client.patch(
            f"/api/watchlist/{item_id}",
            json={"note": "x", "sort_index": 3},
        )
        assert resp.status_code == 200
        body = resp.get_json()["data"]["item"]
        assert body["note"] == "x"
        assert body["sort_index"] == 3

    def test_update_no_fields_422(self, client):
        item_id = _add_mu(client)
        resp = client.patch(f"/api/watchlist/{item_id}", json={})
        assert resp.status_code == 422

    def test_update_unknown_id_404(self, client):
        resp = client.patch(
            "/api/watchlist/no-such-id",
            json={"note": "x"},
        )
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == ErrorCode.NOT_FOUND.value

    def test_update_oversized_note_422(self, client):
        item_id = _add_mu(client)
        resp = client.patch(
            f"/api/watchlist/{item_id}",
            json={"note": "x" * 281},
        )
        assert resp.status_code == 422

    def test_update_store_value_error_translates(self, client, stub_store, monkeypatch):
        """If the store raises ValueError on update (e.g. note too long
        slipped past schema), the route returns 422."""
        original = stub_store.update_item

        def boom(*args, **kwargs):
            raise ValueError("synthetic")

        monkeypatch.setattr(stub_store, "update_item", boom)
        item_id = _add_mu(client)
        resp = client.patch(f"/api/watchlist/{item_id}", json={"note": "ok"})
        assert resp.status_code == 422


class TestDeleteWatchlist:
    def test_delete_success(self, client):
        item_id = _add_mu(client)
        resp = client.delete(f"/api/watchlist/{item_id}")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["deleted"] is True
        # And it's really gone:
        assert client.get("/api/watchlist").get_json()["data"]["items"] == []

    def test_delete_unknown_id_404(self, client):
        resp = client.delete("/api/watchlist/no-such-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /api/watchlist/reorder
# ---------------------------------------------------------------------------


class TestReorderWatchlist:
    def test_reorder_success(self, client):
        a = _add_mu(client)
        b = client.post(
            "/api/watchlist", json={"symbol": "ORCLUSDT"}
        ).get_json()["data"]["item"]["id"]
        c = client.post(
            "/api/watchlist", json={"symbol": "BTCUSDT"}
        ).get_json()["data"]["item"]["id"]

        resp = client.post(
            "/api/watchlist/reorder",
            json={"items": [{"id": c, "sort_index": 0}, {"id": a, "sort_index": 1}, {"id": b, "sort_index": 2}]},
        )
        assert resp.status_code == 200
        listed = client.get("/api/watchlist").get_json()["data"]["items"]
        assert [i["symbol"] for i in listed] == ["BTCUSDT", "MUUSDT", "ORCLUSDT"]
        assert [i["sort_index"] for i in listed] == [0, 1, 2]

    def test_reorder_empty_items_422(self, client):
        resp = client.post("/api/watchlist/reorder", json={"items": []})
        assert resp.status_code == 422

    def test_reorder_duplicate_ids_422(self, client):
        a = _add_mu(client)
        resp = client.post(
            "/api/watchlist/reorder",
            json={"items": [{"id": a, "sort_index": 0}, {"id": a, "sort_index": 1}]},
        )
        assert resp.status_code == 422

    def test_reorder_mismatch_404(self, client):
        a = _add_mu(client)
        resp = client.post(
            "/api/watchlist/reorder",
            json={"items": [{"id": a, "sort_index": 0}, {"id": "missing", "sort_index": 1}]},
        )
        assert resp.status_code == 404

    def test_reorder_store_value_error_translates(self, client, stub_store, monkeypatch):
        """If the store raises ValueError (e.g. duplicate ids slip past the
        route's check), the route translates it to 422."""
        from app.infra.watchlist_store import WatchlistStore

        a = _add_mu(client)
        b = client.post(
            "/api/watchlist", json={"symbol": "ORCLUSDT"}
        ).get_json()["data"]["item"]["id"]

        # Force the store's reorder to raise ValueError on this payload.
        original = stub_store.reorder

        def boom(*args, **kwargs):
            raise ValueError("synthetic")

        monkeypatch.setattr(stub_store, "reorder", boom)
        resp = client.post(
            "/api/watchlist/reorder",
            json={"items": [{"id": b, "sort_index": 0}, {"id": a, "sort_index": 1}]},
        )
        assert resp.status_code == 422
        monkeypatch.setattr(stub_store, "reorder", original)


# ---------------------------------------------------------------------------
# Admin refresh — non-admin path. We don't have a non-local-dev session
# without standing up Supabase auth, so we cover the FORBIDDEN branch via
# a stubbed user dict.
# ---------------------------------------------------------------------------


class TestAdminRefreshForbidden:
    def test_non_admin_branch_is_reachable(self, monkeypatch):
        """The 403 branch lives behind the admin role check. We can't easily
        stand up a non-DISABLE_AUTH Supabase token in unit tests, so we
        invoke ``_is_admin`` directly with a non-admin user dict."""
        from app.api import watchlist_routes as wr

        # Force is_local_dev_mode to False without going through env.
        monkeypatch.setattr(wr, "is_local_dev_mode", lambda: False)
        # Non-admin user dict.
        assert wr._is_admin({"id": "u1", "role": "user"}) is False
        # Admin role still passes.
        assert wr._is_admin({"id": "u1", "role": "admin"}) is True

    def test_admin_branch_in_local_dev(self, monkeypatch):
        from app.api import watchlist_routes as wr

        monkeypatch.setattr(wr, "is_local_dev_mode", lambda: True)
        # Any user (or no user) is admin in local-dev.
        assert wr._is_admin({"id": "u1", "role": "user"}) is True

    def test_refresh_endpoint_returns_403_for_non_admin(
        self, client, monkeypatch
    ):
        """End-to-end: ``POST /api/admin/markets/futures/refresh`` returns
        403 when ``_is_admin`` rejects the user. Stub ``_is_admin`` so we
        don't have to stand up a real Supabase auth path."""
        from app.api import watchlist_routes as wr

        monkeypatch.setattr(wr, "_is_admin", lambda user: False)
        resp = client.post("/api/admin/markets/futures/refresh", json={})
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == ErrorCode.FORBIDDEN.value


class TestStoreHelper:
    def test_store_helper_builds_store_with_cache(self, monkeypatch):
        """The private ``_store`` helper must wire the shared cache's
        ``get_meta`` as the whitelist resolver."""
        from app.api import watchlist_routes as wr
        from app.infra.watchlist_store import WatchlistStore

        monkeypatch.setattr(wr, "get_symbols_cache", lambda: _StubCache())
        s = wr._store()
        assert isinstance(s, WatchlistStore)
        assert s._whitelist_resolver("MUUSDT") is not None


# ---------------------------------------------------------------------------


class TestWatchlistSchemas:
    def test_add_requires_symbol(self):
        from app.domain.watchlist_schemas import WatchlistAddRequest

        with pytest.raises(Exception):
            WatchlistAddRequest.model_validate({})

    def test_add_rejects_lowercase_symbol(self):
        from app.domain.watchlist_schemas import WatchlistAddRequest

        with pytest.raises(Exception):
            WatchlistAddRequest.model_validate({"symbol": "abc"})

    def test_add_rejects_oversized_note(self):
        from app.domain.watchlist_schemas import WatchlistAddRequest

        with pytest.raises(Exception):
            WatchlistAddRequest.model_validate({"symbol": "BTCUSDT", "note": "x" * 281})

    def test_update_negative_sort_index_rejected(self):
        from app.domain.watchlist_schemas import WatchlistUpdateRequest

        with pytest.raises(Exception):
            WatchlistUpdateRequest.model_validate({"sort_index": -1})

    def test_reorder_too_many_items_rejected(self):
        from app.domain.watchlist_schemas import WatchlistReorderRequest

        with pytest.raises(Exception):
            WatchlistReorderRequest.model_validate(
                {"items": [{"id": f"x{i}", "sort_index": i} for i in range(201)]}
            )


# ---------------------------------------------------------------------------
# _build_store_with_cache test helper
# ---------------------------------------------------------------------------


class TestBuildStoreWithCache:
    def test_with_none_cache(self):
        from app.api.watchlist_routes import _build_store_with_cache
        from app.infra.watchlist_store import WatchlistStore

        s = _build_store_with_cache(None)
        assert isinstance(s, WatchlistStore)
        assert s._whitelist_resolver is None

    def test_with_stub_cache(self, stub_cache):
        from app.api.watchlist_routes import _build_store_with_cache
        from app.infra.watchlist_store import WatchlistStore

        s = _build_store_with_cache(stub_cache)
        assert isinstance(s, WatchlistStore)
        # Bound methods compare by underlying function — assert via a probe call.
        assert s._whitelist_resolver("MUUSDT") == stub_cache.get_meta("MUUSDT")


# ---------------------------------------------------------------------------
# /api/markets/futures/quote
# ---------------------------------------------------------------------------


def _stub_fetch_quotes(monkeypatch, payload: dict[str, dict] | Exception):
    """Replace ``fetch_quotes`` in the routes module with a closure."""
    from app.api import watchlist_routes as wr

    def fake(symbols):
        if isinstance(payload, Exception):
            raise payload
        return {s: type("Q", (), {"to_dict": lambda self, s=s: payload[s]})() for s in symbols}

    monkeypatch.setattr(wr, "fetch_quotes", fake)


class TestBatchQuotes:
    def test_returns_merged_quotes(self, client, monkeypatch):
        _stub_fetch_quotes(
            monkeypatch,
            {
                "MUUSDT": {"symbol": "MUUSDT", "lastPrice": 100.5},
                "BTCUSDT": {"symbol": "BTCUSDT", "lastPrice": 50000.0},
            },
        )
        resp = client.get(
            "/api/markets/futures/quote?symbols=MUUSDT,BTCUSDT"
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        data = body["data"]
        assert {q["symbol"] for q in data["quotes"]} == {"MUUSDT", "BTCUSDT"}
        assert data["unknown"] == []

    def test_unknown_symbols_dropped(self, client, monkeypatch):
        _stub_fetch_quotes(
            monkeypatch,
            {"MUUSDT": {"symbol": "MUUSDT", "lastPrice": 1.0}},
        )
        resp = client.get("/api/markets/futures/quote?symbols=MUUSDT,FOOUSDT")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert [q["symbol"] for q in data["quotes"]] == ["MUUSDT"]
        assert data["unknown"] == ["FOOUSDT"]

    def test_empty_symbols_param_returns_422(self, client):
        resp = client.get("/api/markets/futures/quote")
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == ErrorCode.INVALID_PARAMS.value

    def test_only_whitespace_symbols_returns_422(self, client):
        resp = client.get("/api/markets/futures/quote?symbols=%20%2C%20")
        assert resp.status_code == 422

    def test_too_many_symbols_returns_422(self, client):
        # 101 symbols
        big = ",".join(f"S{i}USDT" for i in range(101))
        resp = client.get(f"/api/markets/futures/quote?symbols={big}")
        assert resp.status_code == 422
        assert "too many" in resp.get_json()["error"]["message"]

    def test_upstream_failure_returns_502(self, client, monkeypatch):
        from app.infra.futures_quote import QuoteFetchError

        _stub_fetch_quotes(monkeypatch, QuoteFetchError("boom"))
        resp = client.get("/api/markets/futures/quote?symbols=MUUSDT")
        assert resp.status_code == 502
        assert (
            resp.get_json()["error"]["code"]
            == ErrorCode.MARKET_DATA_UNAVAILABLE.value
        )

    def test_cache_failure_returns_500(self, client, stub_cache, monkeypatch):
        from app.api import watchlist_routes as wr

        # Replace the stub cache with one that raises.
        class BrokenCache(_StubCache):
            def get(self):
                raise RuntimeError("cache down")

        monkeypatch.setattr(wr, "get_symbols_cache", lambda: BrokenCache())
        resp = client.get("/api/markets/futures/quote?symbols=MUUSDT")
        assert resp.status_code == 500
        assert resp.get_json()["error"]["code"] == ErrorCode.INTERNAL_ERROR.value

    def test_all_unknown_skips_upstream(self, client, monkeypatch):
        # If nothing is known, fetch_quotes is invoked with [] and returns {}
        # without hitting the network (the early-return is covered by
        # TestFetchQuotes::test_empty_known_returns_empty_without_http).
        from app.api import watchlist_routes as wr
        seen_symbols: list[list[str]] = []

        def fake(symbols):
            seen_symbols.append(list(symbols))
            return {}

        monkeypatch.setattr(wr, "fetch_quotes", fake)
        resp = client.get("/api/markets/futures/quote?symbols=FOOUSDT,BARUSDT")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["quotes"] == []
        assert resp.get_json()["data"]["unknown"] == ["FOOUSDT", "BARUSDT"]
        assert seen_symbols == [[]]