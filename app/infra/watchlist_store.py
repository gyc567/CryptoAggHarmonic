"""Persistence layer for the watchlist (自选币种) feature.

Each user has up to ``MAX_ITEMS_PER_USER`` rows in ``watchlist_items``,
one per persisted symbol, ordered by ``sort_index`` then ``created_at``.

Two backends are supported:
- **Supabase**: used in production. The service-role client bypasses RLS so
  the routes can enforce ownership in Python before/after each call.
- **In-memory dict**: used when Supabase isn't configured (local dev with
  ``DISABLE_AUTH=1``) or when a Supabase call fails. The semantics mirror
  Supabase closely enough that route logic does not care which is live.

A small set of typed exceptions signals validation failures to the route
layer (``LimitReachedError``, ``DuplicateError``, ``NotFoundError``,
``UnknownSymbolError``). The store never raises generic exceptions for
these expected cases.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from app.infra.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

MAX_ITEMS_PER_USER = 50
MAX_NOTE_LENGTH = 280
DEFAULT_MARKET = "futures"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class WatchlistStoreError(Exception):
    """Base class for watchlist store validation failures."""


class LimitReachedError(WatchlistStoreError):
    """Raised when the user already has ``MAX_ITEMS_PER_USER`` items."""

    def __init__(self, limit: int = MAX_ITEMS_PER_USER):
        super().__init__(f"watchlist already has {limit} items")
        self.limit = limit


class DuplicateError(WatchlistStoreError):
    """Raised when the (market, symbol) pair already exists for the user."""

    def __init__(self, symbol: str, market: str = DEFAULT_MARKET):
        super().__init__(f"{symbol} already in {market} watchlist")
        self.symbol = symbol
        self.market = market


class NotFoundError(WatchlistStoreError):
    """Raised when an item id does not exist or is not owned by the user."""

    def __init__(self, item_id: str):
        super().__init__(f"watchlist item {item_id} not found")
        self.item_id = item_id


class UnknownSymbolError(WatchlistStoreError):
    """Raised when the symbol is not in the cached futures whitelist."""

    def __init__(self, symbol: str):
        super().__init__(f"{symbol} not in cached futures symbol list")
        self.symbol = symbol


# ---------------------------------------------------------------------------
# Symbol metadata accepted by ``create_item``
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolMeta:
    """Lean snapshot of a cached futures symbol.

    Stored alongside the user's row so the frontend can render precision,
    badges and grouping without re-fetching the symbol list.
    """

    symbol: str
    base_asset: str
    quote_asset: str
    contract_type: str
    underlying_type: str | None
    underlying_sub_types: list[str]
    price_precision: int
    quantity_precision: int
    is_tradfi: bool


def symbol_meta_from_cache(entry: dict) -> SymbolMeta:
    """Build a :class:`SymbolMeta` from the dict emitted by the cache.

    Falls back to safe defaults when fields are missing so a stale cache
    entry never crashes a user-visible operation.
    """
    return SymbolMeta(
        symbol=entry["symbol"],
        base_asset=entry.get("baseAsset", ""),
        quote_asset=entry.get("quoteAsset", "USDT"),
        contract_type=entry.get("contractType", "PERPETUAL"),
        underlying_type=entry.get("underlyingType"),
        underlying_sub_types=list(entry.get("underlyingSubTypes") or []),
        price_precision=int(entry.get("pricePrecision", 2)),
        quantity_precision=int(entry.get("quantityPrecision", 3)),
        is_tradfi=bool(entry.get("isTradfi", False)),
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


WhitelistResolver = Callable[[str], SymbolMeta | None]


class WatchlistStore:
    """Persistence for watchlist_items with a Supabase + memory fallback.

    Args:
        whitelist_resolver: Callable that returns the cached
            :class:`SymbolMeta` for a given symbol, or ``None`` if the
            symbol isn't traded on USDⓈ-M. Pass
            ``FuturesSymbolsCache.get_meta`` in production.
    """

    def __init__(self, whitelist_resolver: WhitelistResolver | None = None):
        self._whitelist_resolver: WhitelistResolver | None = whitelist_resolver
        try:
            self._client = get_supabase_client(use_service_role=True)
        except Exception as exc:  # pragma: no cover - env-driven fallback
            logger.warning("Supabase unavailable for WatchlistStore: %s", exc)
            self._client = None

        # Memory fallback: user_id -> dict[item_id -> row]
        self._memory: dict[str, dict[str, dict[str, Any]]] = {}

    # -- backend selection ------------------------------------------------

    def _use_memory(self) -> bool:
        return self._client is None

    # -- public API -------------------------------------------------------

    def list_items(self, user_id: str, market: str = DEFAULT_MARKET) -> list[dict]:
        """Return the user's items, sorted by ``sort_index`` ascending then
        ``created_at`` ascending. Memory backend returns the same order."""
        if self._use_memory():
            return self._list_memory(user_id, market)

        try:
            result = (
                self._client.table("watchlist_items")
                .select("*")
                .eq("user_id", user_id)
                .eq("market", market)
                .order("sort_index", desc=False)
                .order("created_at", desc=False)
                .execute()
            )
            return list(result.data or [])
        except Exception as exc:
            logger.warning("Watchlist list_items failed, falling back to memory: %s", exc)
            return self._list_memory(user_id, market)

    def create_item(
        self,
        user_id: str,
        market: str,
        meta: SymbolMeta,
        note: str = "",
    ) -> dict:
        """Insert a new item.

        Raises:
            UnknownSymbolError: when ``meta`` is not from the cached whitelist.
                In practice this is unreachable because the route validates
                first, but the store layer still enforces it for safety.
            LimitReachedError: when the user already has 50 items.
            DuplicateError: when (user_id, market, symbol) already exists.
            ValueError: when ``note`` exceeds ``MAX_NOTE_LENGTH``.
        """
        self._validate_note(note)
        self._ensure_whitelisted(meta)
        now = _now_iso()
        payload = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "market": market,
            "symbol": meta.symbol,
            "base_asset": meta.base_asset,
            "quote_asset": meta.quote_asset,
            "contract_type": meta.contract_type,
            "underlying_type": meta.underlying_type,
            "underlying_sub_types": list(meta.underlying_sub_types),
            "price_precision": meta.price_precision,
            "quantity_precision": meta.quantity_precision,
            "is_tradfi": meta.is_tradfi,
            "note": note,
            "sort_index": self._next_sort_index(user_id, market),
            "created_at": now,
            "updated_at": now,
        }

        if self._use_memory():
            return self._create_memory(user_id, payload)

        try:
            result = self._client.table("watchlist_items").insert(payload).execute()
            if result.data:
                # Mirror to memory so a later Supabase outage can still
                # fall back without losing the row we just wrote.
                self._create_memory(user_id, payload)
                return result.data[0]
            # Insert returned nothing but didn't raise — fall back to memory
            # so callers always see the row they just wrote.
            return self._create_memory(user_id, payload)
        except Exception as exc:
            # Supabase unique-violation surfaces as an exception. Translate
            # it into DuplicateError so the route can return 409.
            if _is_unique_violation(exc):
                raise DuplicateError(meta.symbol, market) from exc
            logger.warning("Watchlist create_item failed, falling back to memory: %s", exc)
            return self._create_memory(user_id, payload)

    def update_item(
        self,
        item_id: str,
        user_id: str,
        note: str | None = None,
        sort_index: int | None = None,
    ) -> dict:
        """Update ``note`` and/or ``sort_index`` on a single item.

        Raises:
            NotFoundError: when ``item_id`` doesn't belong to ``user_id``.
            ValueError: when neither field is supplied.
        """
        if note is None and sort_index is None:
            raise ValueError("update_item requires note or sort_index")
        if note is not None:
            self._validate_note(note)

        updates: dict[str, Any] = {"updated_at": _now_iso()}
        if note is not None:
            updates["note"] = note
        if sort_index is not None:
            updates["sort_index"] = int(sort_index)

        if self._use_memory():
            return self._update_memory(item_id, user_id, updates)

        try:
            result = (
                self._client.table("watchlist_items")
                .update(updates)
                .eq("id", item_id)
                .eq("user_id", user_id)
                .execute()
            )
            rows = list(result.data or [])
            if not rows:
                raise NotFoundError(item_id)
            return rows[0]
        except NotFoundError:
            raise
        except Exception as exc:
            logger.warning("Watchlist update_item failed, falling back to memory: %s", exc)
            return self._update_memory(item_id, user_id, updates)

    def delete_item(self, item_id: str, user_id: str) -> bool:
        """Remove an item. Returns False (and raises :class:`NotFoundError`)
        if the id doesn't exist or belongs to another user."""
        if self._use_memory():
            return self._delete_memory(item_id, user_id)

        try:
            result = (
                self._client.table("watchlist_items")
                .delete()
                .eq("id", item_id)
                .eq("user_id", user_id)
                .execute()
            )
            rows = list(result.data or [])
            if not rows:
                raise NotFoundError(item_id)
            return True
        except NotFoundError:
            raise
        except Exception as exc:
            logger.warning("Watchlist delete_item failed, falling back to memory: %s", exc)
            return self._delete_memory(item_id, user_id)

    def reorder(
        self,
        user_id: str,
        market: str,
        ordered_ids: list[str],
    ) -> list[dict]:
        """Bulk-update ``sort_index`` so that ``ordered_ids`` reflects the
        user's intended order. Items not in ``ordered_ids`` keep their
        existing ``sort_index`` shifted to follow the re-ordered block.

        Raises:
            NotFoundError: when an id in ``ordered_ids`` isn't owned by the
                user or doesn't belong to ``market``.
            ValueError: when ``ordered_ids`` contains duplicates or omits
                ids the user currently owns.
        """
        existing = self.list_items(user_id=user_id, market=market)
        existing_by_id = {row["id"]: row for row in existing}
        if len(set(ordered_ids)) != len(ordered_ids):
            raise ValueError("reorder received duplicate ids")
        if sorted(ordered_ids) != sorted(existing_by_id):
            missing = set(existing_by_id) - set(ordered_ids)
            extra = set(ordered_ids) - set(existing_by_id)
            raise NotFoundError(
                f"reorder ids mismatch: missing={sorted(missing)} extra={sorted(extra)}"
            )

        now = _now_iso()
        updates: list[dict[str, Any]] = []
        new_rows: list[dict] = []
        for index, item_id in enumerate(ordered_ids):
            patch = {
                "id": item_id,
                "user_id": user_id,
                "market": market,
                "sort_index": index,
                "updated_at": now,
            }
            updates.append(patch)

        if self._use_memory():
            return self._reorder_memory(user_id, market, updates)

        # Supabase: do a single UPDATE per id (PostgREST has no bulk
        # primary-key UPDATE). Failures abort early and raise.
        new_rows = []
        for patch in updates:
            try:
                result = (
                    self._client.table("watchlist_items")
                    .update({"sort_index": patch["sort_index"], "updated_at": patch["updated_at"]})
                    .eq("id", patch["id"])
                    .eq("user_id", user_id)
                    .execute()
                )
                rows = list(result.data or [])
                if not rows:
                    raise NotFoundError(patch["id"])
                new_rows.append(rows[0])
            except NotFoundError:
                raise
            except Exception as exc:
                logger.warning("Watchlist reorder failed, falling back to memory: %s", exc)
                return self._reorder_memory(user_id, market, updates)

        # Re-sort by new sort_index to match the requested order.
        new_rows.sort(key=lambda r: r["sort_index"])
        return new_rows

    # -- validation -------------------------------------------------------

    def _validate_note(self, note: str) -> None:
        if note is None:
            return
        if len(note) > MAX_NOTE_LENGTH:
            raise ValueError(f"note exceeds {MAX_NOTE_LENGTH} chars")

    def _ensure_whitelisted(self, meta: SymbolMeta) -> None:
        if self._whitelist_resolver is None:
            return  # caller is trusted when no resolver is injected
        resolved = self._whitelist_resolver(meta.symbol)
        if resolved is None or resolved.quote_asset != meta.quote_asset:
            raise UnknownSymbolError(meta.symbol)

    def _next_sort_index(self, user_id: str, market: str) -> int:
        existing = self.list_items(user_id=user_id, market=market)
        if not existing:
            return 0
        return max(int(row.get("sort_index", 0)) for row in existing) + 1

    # -- memory backend ---------------------------------------------------

    def _list_memory(self, user_id: str, market: str) -> list[dict]:
        rows = [
            row
            for row in self._memory.get(user_id, {}).values()
            if row.get("market") == market
        ]
        rows.sort(key=lambda r: (int(r.get("sort_index", 0)), r.get("created_at") or ""))
        return rows

    def _create_memory(self, user_id: str, payload: dict) -> dict:
        user_rows = self._memory.setdefault(user_id, {})
        if any(
            r.get("market") == payload["market"] and r.get("symbol") == payload["symbol"]
            for r in user_rows.values()
        ):
            raise DuplicateError(payload["symbol"], payload["market"])
        if len(user_rows) >= MAX_ITEMS_PER_USER:
            raise LimitReachedError(MAX_ITEMS_PER_USER)
        user_rows[payload["id"]] = dict(payload)
        return dict(payload)

    def _update_memory(self, item_id: str, user_id: str, updates: dict) -> dict:
        user_rows = self._memory.get(user_id, {})
        row = user_rows.get(item_id)
        if row is None:
            raise NotFoundError(item_id)
        row.update(updates)
        user_rows[item_id] = row
        return dict(row)

    def _delete_memory(self, item_id: str, user_id: str) -> bool:
        user_rows = self._memory.get(user_id, {})
        if item_id not in user_rows:
            raise NotFoundError(item_id)
        del user_rows[item_id]
        return True

    def _reorder_memory(
        self,
        user_id: str,
        market: str,
        updates: list[dict],
    ) -> list[dict]:
        rows: list[dict] = []
        for patch in updates:
            updated = self._update_memory(
                patch["id"],
                user_id,
                {"sort_index": patch["sort_index"], "updated_at": patch["updated_at"]},
            )
            rows.append(updated)
        rows.sort(key=lambda r: r["sort_index"])
        return rows


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_unique_violation(exc: Exception) -> bool:
    """Heuristic: detect the ``UNIQUE (user_id, market, symbol)`` violation.

    Supabase surfaces this as ``postgrest.exceptions.APIError`` carrying
    a 409 status with the unique-constraint code in the message. We keep
    this conservative so a generic network failure never maps to a 409.
    """
    msg = str(exc).lower()
    if "duplicate key" in msg or "unique constraint" in msg or "23505" in msg:
        return True
    code = getattr(exc, "code", None)
    if code in ("23505", "P2002"):
        return True
    return False