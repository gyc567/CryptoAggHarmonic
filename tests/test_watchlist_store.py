"""Tests for ``app.infra.watchlist_store``.

Coverage target: 100% of the store module. We force the memory fallback
by passing a stub client that always fails, which exercises the same code
path as production with Supabase unavailable (and lets us assert exact
data shapes). A few tests also drive the Supabase path with a stub client
to confirm the error-translation logic (unique-violation → DuplicateError).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.infra.watchlist_store import (
    DEFAULT_MARKET,
    DuplicateError,
    LimitReachedError,
    MAX_ITEMS_PER_USER,
    MAX_NOTE_LENGTH,
    NotFoundError,
    SymbolMeta,
    UnknownSymbolError,
    WatchlistStore,
    symbol_meta_from_cache,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_meta() -> SymbolMeta:
    return SymbolMeta(
        symbol="MUUSDT",
        base_asset="MU",
        quote_asset="USDT",
        contract_type="TRADIFI_PERPETUAL",
        underlying_type="EQUITY",
        underlying_sub_types=["TradFi"],
        price_precision=3,
        quantity_precision=0,
        is_tradfi=True,
    )


@pytest.fixture
def second_meta() -> SymbolMeta:
    return SymbolMeta(
        symbol="ORCLUSDT",
        base_asset="ORCL",
        quote_asset="USDT",
        contract_type="TRADIFI_PERPETUAL",
        underlying_type="EQUITY",
        underlying_sub_types=["TradFi"],
        price_precision=3,
        quantity_precision=0,
        is_tradfi=True,
    )


@pytest.fixture
def crypto_meta() -> SymbolMeta:
    return SymbolMeta(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        contract_type="PERPETUAL",
        underlying_type="COIN",
        underlying_sub_types=["Layer-1"],
        price_precision=2,
        quantity_precision=3,
        is_tradfi=False,
    )


def _to_dict(meta: SymbolMeta) -> dict[str, Any]:
    return {
        "symbol": meta.symbol,
        "base_asset": meta.base_asset,
        "quote_asset": meta.quote_asset,
        "contract_type": meta.contract_type,
        "underlying_type": meta.underlying_type,
        "underlying_sub_types": list(meta.underlying_sub_types),
        "price_precision": meta.price_precision,
        "quantity_precision": meta.quantity_precision,
        "is_tradfi": meta.is_tradfi,
    }


@pytest.fixture
def whitelist(sample_meta, second_meta, crypto_meta):
    """Resolver that returns SymbolMeta for known symbols, else None."""

    def resolve(symbol: str) -> SymbolMeta | None:
        known = {
            "MUUSDT": sample_meta,
            "ORCLUSDT": second_meta,
            "BTCUSDT": crypto_meta,
        }
        return known.get(symbol)

    return resolve


@pytest.fixture
def store(whitelist) -> WatchlistStore:
    """A store with no Supabase client (forces memory fallback)."""
    s = WatchlistStore(whitelist_resolver=whitelist)
    s._client = None  # explicit; __init__ already tries Supabase
    return s


@pytest.fixture
def supabase_store(whitelist):
    """A store with a controllable Supabase stub."""
    s = WatchlistStore(whitelist_resolver=whitelist)
    s._client = _StubClient()
    return s


# ---------------------------------------------------------------------------
# Stub Supabase client
# ---------------------------------------------------------------------------


class _StubTable:
    """Minimal PostgREST-style query builder. Supports insert / select /
    update / delete / eq / order / execute. Behavior is driven by
    ``self._rows`` (a list of dicts) and ``self._client._always_error`` /
    ``self._client._next_error``."""

    def __init__(self, client: "_StubClient", name: str):
        self._client = client
        self._name = name
        self._filters: list[tuple[str, Any]] = []
        self._orders: list[tuple[str, bool]] = []
        self._payload: dict | list[dict] | None = None
        self._op = "select"

    # terminal
    def execute(self):
        if self._client._always_error is not None:
            raise self._client._always_error
        err = self._client._next_error
        if err is not None:
            self._client._next_error = None
            raise err
        if self._op == "insert":
            payload = self._payload
            if isinstance(payload, list):
                for row in payload:
                    self._client._rows[self._name].append(row)
                return _Result(payload)
            self._client._rows[self._name].append(payload)
            return _Result([payload])
        if self._op == "update":
            patched = self._payload or {}
            hits = []
            for row in self._client._rows[self._name]:
                if all(row.get(k) == v for k, v in self._filters):
                    row.update(patched)
                    hits.append(dict(row))
            return _Result(hits)
        if self._op == "delete":
            survivors = []
            removed = []
            for row in self._client._rows[self._name]:
                if all(row.get(k) == v for k, v in self._filters):
                    removed.append(row)
                else:
                    survivors.append(row)
            self._client._rows[self._name] = survivors
            return _Result(removed)
        # select
        out = [dict(r) for r in self._client._rows[self._name] if all(r.get(k) == v for k, v in self._filters)]
        for col, desc in reversed(self._orders):
            out.sort(key=lambda r: r.get(col) or "", reverse=desc)
        return _Result(out)

    # chaining
    def insert(self, payload: dict | list[dict]):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload: dict):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def select(self, *_args, **_kwargs):
        self._op = "select"
        return self

    def eq(self, col: str, value: Any):
        self._filters.append((col, value))
        return self

    def order(self, col: str, desc: bool = False):
        self._orders.append((col, desc))
        return self


class _Result:
    def __init__(self, data):
        self.data = data


class _StubClient:
    def __init__(self):
        self._rows: dict[str, list[dict]] = {"watchlist_items": []}
        self._next_error: Exception | None = None
        self._always_error: Exception | None = None

    def table(self, name: str):
        return _StubTable(self, name)


class _UniqueViolation(Exception):
    def __init__(self):
        super().__init__("duplicate key value violates unique constraint 23505")
        self.code = "23505"


# ---------------------------------------------------------------------------
# symbol_meta_from_cache
# ---------------------------------------------------------------------------


class TestSymbolMetaFromCache:
    def test_full_entry(self):
        meta = symbol_meta_from_cache(
            {
                "symbol": "MUUSDT",
                "baseAsset": "MU",
                "quoteAsset": "USDT",
                "contractType": "TRADIFI_PERPETUAL",
                "underlyingType": "EQUITY",
                "underlyingSubTypes": ["TradFi"],
                "pricePrecision": 3,
                "quantityPrecision": 0,
                "isTradfi": True,
            }
        )
        assert meta.symbol == "MUUSDT"
        assert meta.base_asset == "MU"
        assert meta.is_tradfi is True
        assert meta.underlying_sub_types == ["TradFi"]

    def test_minimal_entry_uses_defaults(self):
        meta = symbol_meta_from_cache({"symbol": "XUSDT"})
        assert meta.quote_asset == "USDT"
        assert meta.contract_type == "PERPETUAL"
        assert meta.price_precision == 2
        assert meta.quantity_precision == 3
        assert meta.underlying_type is None
        assert meta.underlying_sub_types == []
        assert meta.is_tradfi is False

    def test_none_sub_types_becomes_empty_list(self):
        meta = symbol_meta_from_cache({"symbol": "X", "underlyingSubTypes": None})
        assert meta.underlying_sub_types == []


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_limit_reached_carries_limit(self):
        err = LimitReachedError(limit=50)
        assert err.limit == 50
        assert "50" in str(err)
        assert isinstance(err, Exception)

    def test_duplicate_carries_symbol_and_market(self):
        err = DuplicateError(symbol="MUUSDT", market="futures")
        assert err.symbol == "MUUSDT"
        assert err.market == "futures"

    def test_not_found_carries_id(self):
        err = NotFoundError(item_id="abc-123")
        assert err.item_id == "abc-123"

    def test_unknown_symbol_carries_symbol(self):
        err = UnknownSymbolError(symbol="FOOUSDT")
        assert err.symbol == "FOOUSDT"


# ---------------------------------------------------------------------------
# Memory backend — list / create / update / delete
# ---------------------------------------------------------------------------


class TestMemoryCreateAndList:
    def test_create_returns_inserted_row(self, store, sample_meta):
        row = store.create_item("u1", DEFAULT_MARKET, sample_meta, note="hello")
        assert row["symbol"] == "MUUSDT"
        assert row["user_id"] == "u1"
        assert row["market"] == DEFAULT_MARKET
        assert row["note"] == "hello"
        assert row["sort_index"] == 0
        assert row["is_tradfi"] is True
        assert row["base_asset"] == "MU"

    def test_create_assigns_increasing_sort_index(self, store, sample_meta, second_meta):
        store.create_item("u1", DEFAULT_MARKET, sample_meta)
        second = store.create_item("u1", DEFAULT_MARKET, second_meta)
        assert second["sort_index"] == 1

    def test_list_empty(self, store):
        assert store.list_items("u1") == []

    def test_list_orders_by_sort_index(self, store, sample_meta, second_meta):
        a = store.create_item("u1", DEFAULT_MARKET, sample_meta)
        b = store.create_item("u1", DEFAULT_MARKET, second_meta)
        listed = store.list_items("u1")
        assert [r["id"] for r in listed] == [a["id"], b["id"]]

    def test_list_filters_by_market(self, store, sample_meta):
        store.create_item("u1", "futures", sample_meta)
        store.create_item("u1", "spot", sample_meta)
        assert len(store.list_items("u1", market="futures")) == 1
        assert len(store.list_items("u1", market="spot")) == 1

    def test_list_segregates_users(self, store, sample_meta):
        store.create_item("u1", DEFAULT_MARKET, sample_meta)
        store.create_item("u2", DEFAULT_MARKET, sample_meta)
        assert len(store.list_items("u1")) == 1
        assert len(store.list_items("u2")) == 1

    def test_create_rejects_oversized_note(self, store, sample_meta):
        """Note longer than MAX_NOTE_LENGTH must be rejected at the store."""
        long = "x" * (MAX_NOTE_LENGTH + 1)
        with pytest.raises(ValueError):
            store.create_item("u1", DEFAULT_MARKET, sample_meta, note=long)


class TestMemoryValidation:
    def test_duplicate_raises(self, store, sample_meta):
        store.create_item("u1", DEFAULT_MARKET, sample_meta)
        with pytest.raises(DuplicateError) as ei:
            store.create_item("u1", DEFAULT_MARKET, sample_meta)
        assert ei.value.symbol == "MUUSDT"

    def test_limit_reached_after_50(self):
        """50 items succeeds; 51st raises LimitReachedError."""
        # Use a permissive whitelist (accept any symbol) so we can insert
        # 50 distinct synthetic symbols without pre-seeding the whitelist.
        store = WatchlistStore(whitelist_resolver=lambda symbol: SymbolMeta(
            symbol=symbol,
            base_asset=symbol[:-4],
            quote_asset="USDT",
            contract_type="PERPETUAL",
            underlying_type="COIN",
            underlying_sub_types=[],
            price_precision=2,
            quantity_precision=3,
            is_tradfi=False,
        ))
        store._client = None
        for i in range(MAX_ITEMS_PER_USER):
            meta = SymbolMeta(
                symbol=f"SYM{i:02d}USDT",
                base_asset=f"S{i:02d}",
                quote_asset="USDT",
                contract_type="PERPETUAL",
                underlying_type="COIN",
                underlying_sub_types=[],
                price_precision=2,
                quantity_precision=3,
                is_tradfi=False,
            )
            store.create_item("u1", DEFAULT_MARKET, meta)
        one_more = SymbolMeta(
            symbol="OVERFLOWUSDT",
            base_asset="OV",
            quote_asset="USDT",
            contract_type="PERPETUAL",
            underlying_type="COIN",
            underlying_sub_types=[],
            price_precision=2,
            quantity_precision=3,
            is_tradfi=False,
        )
        with pytest.raises(LimitReachedError):
            store.create_item("u1", DEFAULT_MARKET, one_more)

    def test_unknown_symbol_raises(self, sample_meta):
        s = WatchlistStore(whitelist_resolver=lambda symbol: None)
        s._client = None
        with pytest.raises(UnknownSymbolError):
            s.create_item("u1", DEFAULT_MARKET, sample_meta)

    def test_unknown_symbol_quote_mismatch_raises(self, sample_meta):
        # Whitelist returns a different quote asset → reject.
        wrong = SymbolMeta(
            symbol="MUUSDT",
            base_asset="MU",
            quote_asset="USDC",  # wrong
            contract_type="TRADIFI_PERPETUAL",
            underlying_type="EQUITY",
            underlying_sub_types=[],
            price_precision=3,
            quantity_precision=0,
            is_tradfi=True,
        )

        def resolve(symbol):
            return wrong

        s = WatchlistStore(whitelist_resolver=resolve)
        s._client = None
        with pytest.raises(UnknownSymbolError):
            s.create_item("u1", DEFAULT_MARKET, sample_meta)

    def test_no_resolver_skips_whitelist_check(self, sample_meta):
        s = WatchlistStore(whitelist_resolver=None)
        s._client = None
        row = s.create_item("u1", DEFAULT_MARKET, sample_meta)
        assert row["symbol"] == "MUUSDT"


# ---------------------------------------------------------------------------
# Memory backend — update / delete
# ---------------------------------------------------------------------------


class TestMemoryUpdateAndDelete:
    def test_update_note(self, store, sample_meta):
        row = store.create_item("u1", DEFAULT_MARKET, sample_meta)
        updated = store.update_item(row["id"], "u1", note="new note")
        assert updated["note"] == "new note"

    def test_update_sort_index(self, store, sample_meta):
        row = store.create_item("u1", DEFAULT_MARKET, sample_meta)
        updated = store.update_item(row["id"], "u1", sort_index=10)
        assert updated["sort_index"] == 10

    def test_update_both(self, store, sample_meta):
        row = store.create_item("u1", DEFAULT_MARKET, sample_meta)
        updated = store.update_item(row["id"], "u1", note="x", sort_index=5)
        assert updated["note"] == "x"
        assert updated["sort_index"] == 5

    def test_update_no_fields_raises_value_error(self, store, sample_meta):
        row = store.create_item("u1", DEFAULT_MARKET, sample_meta)
        with pytest.raises(ValueError):
            store.update_item(row["id"], "u1")

    def test_update_note_too_long_raises(self, store, sample_meta):
        row = store.create_item("u1", DEFAULT_MARKET, sample_meta)
        with pytest.raises(ValueError):
            store.update_item(row["id"], "u1", note="x" * (MAX_NOTE_LENGTH + 1))

    def test_update_not_found(self, store):
        with pytest.raises(NotFoundError):
            store.update_item("missing-id", "u1", note="x")

    def test_update_other_users_item_raises_not_found(self, store, sample_meta):
        row = store.create_item("u1", DEFAULT_MARKET, sample_meta)
        with pytest.raises(NotFoundError):
            store.update_item(row["id"], "u2", note="x")

    def test_delete_existing(self, store, sample_meta):
        row = store.create_item("u1", DEFAULT_MARKET, sample_meta)
        assert store.delete_item(row["id"], "u1") is True
        assert store.list_items("u1") == []

    def test_delete_missing_raises_not_found(self, store):
        with pytest.raises(NotFoundError):
            store.delete_item("missing-id", "u1")

    def test_delete_other_users_item_raises_not_found(self, store, sample_meta):
        row = store.create_item("u1", DEFAULT_MARKET, sample_meta)
        with pytest.raises(NotFoundError):
            store.delete_item(row["id"], "u2")


# ---------------------------------------------------------------------------
# Memory backend — reorder
# ---------------------------------------------------------------------------


class TestMemoryReorder:
    def test_reorder_persists_sort_index(self, store, sample_meta, second_meta, crypto_meta):
        a = store.create_item("u1", DEFAULT_MARKET, sample_meta)
        b = store.create_item("u1", DEFAULT_MARKET, second_meta)
        c = store.create_item("u1", DEFAULT_MARKET, crypto_meta)
        reordered = store.reorder("u1", DEFAULT_MARKET, [c["id"], a["id"], b["id"]])
        assert [r["symbol"] for r in reordered] == ["BTCUSDT", "MUUSDT", "ORCLUSDT"]
        assert [r["sort_index"] for r in reordered] == [0, 1, 2]
        listed = store.list_items("u1")
        assert [r["symbol"] for r in listed] == ["BTCUSDT", "MUUSDT", "ORCLUSDT"]

    def test_reorder_missing_id_raises(self, store, sample_meta):
        a = store.create_item("u1", DEFAULT_MARKET, sample_meta)
        with pytest.raises(NotFoundError):
            store.reorder("u1", DEFAULT_MARKET, ["non-existent", a["id"]])

    def test_reorder_extra_id_raises(self, store, sample_meta):
        a = store.create_item("u1", DEFAULT_MARKET, sample_meta)
        with pytest.raises(NotFoundError):
            store.reorder("u1", DEFAULT_MARKET, [a["id"], "extra"])

    def test_reorder_duplicate_ids_raises(self, store, sample_meta):
        a = store.create_item("u1", DEFAULT_MARKET, sample_meta)
        with pytest.raises(ValueError):
            store.reorder("u1", DEFAULT_MARKET, [a["id"], a["id"]])

    def test_reorder_empty(self, store):
        assert store.reorder("u1", DEFAULT_MARKET, []) == []


# ---------------------------------------------------------------------------
# Supabase backend — covers the fallback paths and unique-violation handling
# ---------------------------------------------------------------------------


class TestSupabaseFallback:
    def test_list_falls_back_on_failure(self, supabase_store, sample_meta, monkeypatch):
        # Populate memory first so the fallback has something to return.
        supabase_store._create_memory("u1", {
            "id": "row-1", "user_id": "u1", "market": DEFAULT_MARKET,
            "symbol": "MUUSDT", "base_asset": "MU", "quote_asset": "USDT",
            "contract_type": "PERPETUAL", "underlying_type": "EQUITY",
            "underlying_sub_types": [], "price_precision": 3,
            "quantity_precision": 0, "is_tradfi": True,
            "note": "", "sort_index": 0,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        })
        # Make the supabase .table() raise on call → triggers fallback.
        monkeypatch.setattr(
            supabase_store._client, "table",
            lambda name: (_ for _ in ()).throw(RuntimeError("db down")),
        )
        listed = supabase_store.list_items("u1")
        assert len(listed) == 1
        assert listed[0]["symbol"] == "MUUSDT"

    def test_create_falls_back_on_failure(self, supabase_store, sample_meta, monkeypatch):
        monkeypatch.setattr(
            supabase_store._client, "table",
            lambda name: (_ for _ in ()).throw(RuntimeError("db down")),
        )
        row = supabase_store.create_item("u1", DEFAULT_MARKET, sample_meta)
        assert row["symbol"] == "MUUSDT"

    def test_create_translates_unique_violation(self, whitelist, sample_meta):
        """A Supabase unique-violation on insert must surface as DuplicateError."""
        s = WatchlistStore(whitelist_resolver=whitelist)
        # Fresh stub client with persistent-always-error set to the violation.
        s._client = _StubClient()
        s._client._always_error = _UniqueViolation()
        with pytest.raises(DuplicateError):
            s.create_item("u1", DEFAULT_MARKET, sample_meta)

    def test_create_translates_p2002_violation(self, whitelist, sample_meta):
        class _P2002(Exception):
            code = "P2002"
            def __str__(self):
                return "Unique constraint failed"

        s = WatchlistStore(whitelist_resolver=whitelist)
        s._client = _StubClient()
        s._client._always_error = _P2002()
        with pytest.raises(DuplicateError):
            s.create_item("u1", DEFAULT_MARKET, sample_meta)

    def test_create_translates_generic_message_violation(self, whitelist, sample_meta):
        s = WatchlistStore(whitelist_resolver=whitelist)
        s._client = _StubClient()
        s._client._always_error = RuntimeError("duplicate key value violates unique constraint")
        with pytest.raises(DuplicateError):
            s.create_item("u1", DEFAULT_MARKET, sample_meta)

    def test_create_no_data_returned_falls_back(self, supabase_store, sample_meta):
        # Configure the stub to return empty data on insert.
        original_table = supabase_store._client.table

        class _EmptyInsertTable(_StubTable):
            def execute(self):
                if self._op == "insert":
                    return _Result([])
                return super().execute()

        supabase_store._client._rows["watchlist_items"] = []

        def table(name):
            return _EmptyInsertTable(supabase_store._client, name)

        supabase_store._client.table = table
        row = supabase_store.create_item("u1", DEFAULT_MARKET, sample_meta)
        assert row["symbol"] == "MUUSDT"

    def test_update_falls_back_on_failure(self, supabase_store, sample_meta):
        """First insert succeeds, then we make all subsequent calls fail."""
        row = supabase_store.create_item("u1", DEFAULT_MARKET, sample_meta)
        # Now switch to always-error so update falls back to memory.
        supabase_store._client._always_error = RuntimeError("db down")
        updated = supabase_store.update_item(row["id"], "u1", note="fallback")
        assert updated["note"] == "fallback"

    def test_update_missing_row_supabase_raises_not_found(self, supabase_store):
        with pytest.raises(NotFoundError):
            supabase_store.update_item("missing", "u1", note="x")

    def test_update_supabase_success_returns_row(self, supabase_store, sample_meta):
        """When Supabase update succeeds, return the row from the response."""
        row = supabase_store.create_item("u1", DEFAULT_MARKET, sample_meta)
        updated = supabase_store.update_item(row["id"], "u1", note="hi")
        assert updated["note"] == "hi"

    def test_delete_supabase_success(self, supabase_store, sample_meta):
        """When Supabase delete succeeds, return True."""
        row = supabase_store.create_item("u1", DEFAULT_MARKET, sample_meta)
        assert supabase_store.delete_item(row["id"], "u1") is True

    def test_delete_falls_back_on_failure(self, supabase_store, sample_meta):
        row = supabase_store.create_item("u1", DEFAULT_MARKET, sample_meta)
        supabase_store._client._always_error = RuntimeError("db down")
        assert supabase_store.delete_item(row["id"], "u1") is True

    def test_delete_missing_supabase_raises(self, supabase_store):
        with pytest.raises(NotFoundError):
            supabase_store.delete_item("missing", "u1")

    def test_reorder_falls_back_on_failure(self, supabase_store, sample_meta, second_meta):
        a = supabase_store.create_item("u1", DEFAULT_MARKET, sample_meta)
        b = supabase_store.create_item("u1", DEFAULT_MARKET, second_meta)
        supabase_store._client._always_error = RuntimeError("db down")
        reordered = supabase_store.reorder("u1", DEFAULT_MARKET, [b["id"], a["id"]])
        assert [r["symbol"] for r in reordered] == ["ORCLUSDT", "MUUSDT"]

    def test_reorder_supabase_success(self, supabase_store, sample_meta, second_meta):
        """Happy path: Supabase reorder succeeds, rows come back sorted."""
        a = supabase_store.create_item("u1", DEFAULT_MARKET, sample_meta)
        b = supabase_store.create_item("u1", DEFAULT_MARKET, second_meta)
        reordered = supabase_store.reorder("u1", DEFAULT_MARKET, [b["id"], a["id"]])
        assert [r["symbol"] for r in reordered] == ["ORCLUSDT", "MUUSDT"]
        assert [r["sort_index"] for r in reordered] == [0, 1]

    def test_reorder_missing_in_supabase_raises(self, supabase_store, sample_meta):
        a = supabase_store.create_item("u1", DEFAULT_MARKET, sample_meta)
        # Manually remove from supabase rows so the reorder select returns [a],
        # but we still pass [a, "missing"].
        supabase_store._client._rows["watchlist_items"] = []
        supabase_store._memory["u1"] = {a["id"]: a}
        with pytest.raises(NotFoundError):
            supabase_store.reorder("u1", DEFAULT_MARKET, [a["id"], "missing"])

    def test_reorder_one_row_missing_supabase_raises(self, supabase_store, sample_meta, second_meta):
        """If one id in the batch is not in Supabase, the whole reorder fails.

        We add a "phantom" row to both stub and memory so the mismatch check
        passes, then make the second update return empty rows so the
        per-row NotFoundError fires (covering the ``raise`` re-raise path).
        """
        a = supabase_store.create_item("u1", DEFAULT_MARKET, sample_meta)
        b = supabase_store.create_item("u1", DEFAULT_MARKET, second_meta)
        # Inject a phantom row that exists in both stub and memory so the
        # reorder's mismatch check passes (id list matches), but the
        # phantom will be removed from the stub right before the per-row
        # update runs.
        phantom_id = "phantom-id"
        phantom = {
            "id": phantom_id, "user_id": "u1", "market": DEFAULT_MARKET,
            "symbol": "PHANTOMUSDT", "sort_index": 0,
        }
        supabase_store._client._rows["watchlist_items"].append(phantom)
        supabase_store._memory["u1"][phantom_id] = phantom

        # Patch update to return empty rows when called for phantom_id.
        original_table = supabase_store._client.table

        def patched_table(name):
            tbl = _StubTable(supabase_store._client, name)

            def selective_execute():
                if tbl._op == "update":
                    row_ids = [r.get("id") for r in tbl._client._rows["watchlist_items"]]
                    if phantom_id in row_ids:
                        # Remove the phantom row so update returns 0 hits.
                        tbl._client._rows["watchlist_items"] = [
                            r for r in tbl._client._rows["watchlist_items"] if r.get("id") != phantom_id
                        ]
                return _StubTable.execute(tbl)

            tbl.execute = selective_execute
            return tbl

        supabase_store._client.table = patched_table
        with pytest.raises(NotFoundError):
            supabase_store.reorder("u1", DEFAULT_MARKET, [a["id"], phantom_id, b["id"]])


# ---------------------------------------------------------------------------
# is_unique_violation helper
# ---------------------------------------------------------------------------


class TestIsUniqueViolation:
    @staticmethod
    def fn(exc):
        from app.infra.watchlist_store import _is_unique_violation
        return _is_unique_violation(exc)

    def test_matches_duplicate_key_message(self):
        assert self.fn(RuntimeError("duplicate key value")) is True

    def test_matches_unique_constraint_message(self):
        assert self.fn(RuntimeError("violates unique constraint")) is True

    def test_matches_23505_code(self):
        exc = RuntimeError("whatever")
        exc.code = "23505"
        assert self.fn(exc) is True

    def test_matches_p2002_code(self):
        exc = RuntimeError("whatever")
        exc.code = "P2002"
        assert self.fn(exc) is True

    def test_does_not_match_generic_error(self):
        assert self.fn(RuntimeError("connection refused")) is False

    def test_does_not_match_when_no_code(self):
        exc = RuntimeError("oops")
        assert self.fn(exc) is False


# ---------------------------------------------------------------------------
# _validate_note helper (line 380: the ``note is None`` short-circuit)
# ---------------------------------------------------------------------------


class TestValidateNote:
    def test_none_is_accepted(self):
        """``None`` skips length validation entirely (used by update_item when
        only sort_index is being changed)."""
        s = WatchlistStore(whitelist_resolver=None)
        s._client = None
        s._validate_note(None)  # should not raise