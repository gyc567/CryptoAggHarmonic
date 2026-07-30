"""Watchlist (自选币种) HTTP routes.

Endpoints (all under ``require_auth`` except the admin refresh):

* ``GET    /api/markets/futures/symbols``  — cached USDT-m symbols, ``?q=`` filter
* ``POST   /api/admin/markets/futures/refresh`` — force-refresh the cache (admin)
* ``GET    /api/watchlist``                — current user's items
* ``POST   /api/watchlist``                — add an item
* ``PATCH  /api/watchlist/<id>``           — update note / sort_index
* ``DELETE /api/watchlist/<id>``           — remove an item
* ``POST   /api/watchlist/reorder``        — bulk reorder

Error mapping:
    :class:`UnknownSymbolError`  -> 422 WATCHLIST_UNKNOWN_SYMBOL
    :class:`LimitReachedError`   -> 422 WATCHLIST_LIMIT_REACHED
    :class:`DuplicateError`      -> 409 DUPLICATE_SYMBOL
    :class:`NotFoundError`       -> 404 NOT_FOUND

The blueprint is registered as ``watchlist_bp`` by ``app/main.py``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from flask import Blueprint, request

from app.api.auth import is_local_dev_mode, require_auth
from app.api.responses import error as _error
from app.api.responses import success as _success
from app.api.validation import parse_request
from app.domain.enums import ErrorCode
from app.domain.watchlist_schemas import (
    WatchlistAddRequest,
    WatchlistRefreshRequest,
    WatchlistReorderRequest,
    WatchlistUpdateRequest,
)
from app.infra.futures_symbols_cache import FuturesSymbolsCache, get_symbols_cache
from app.infra.watchlist_store import (
    DEFAULT_MARKET,
    DuplicateError,
    LimitReachedError,
    MAX_ITEMS_PER_USER,
    NotFoundError,
    SymbolMeta,
    UnknownSymbolError,
    WatchlistStore,
    symbol_meta_from_cache,
)

logger = logging.getLogger(__name__)

watchlist_bp = Blueprint("watchlist", __name__, url_prefix="/api")


def _user_id(user: dict[str, Any]) -> str:
    return str(user["id"])


def _store() -> WatchlistStore:
    """Build a store wired to the shared cache.

    Lazy import keeps test isolation: tests can monkeypatch
    ``get_symbols_cache`` to inject a stub before the route is hit.
    """
    cache = get_symbols_cache()
    return WatchlistStore(whitelist_resolver=cache.get_meta)


# ---------------------------------------------------------------------------
# Markets — symbol search & admin refresh
# ---------------------------------------------------------------------------


@watchlist_bp.route("/markets/futures/symbols", methods=["GET"])
@require_auth
def list_futures_symbols(user):  # noqa: ARG001 — user injected by require_auth
    """Return cached USDⓈ-M symbols, optionally filtered by ``?q=``."""
    q = (request.args.get("q") or "").strip().upper()
    try:
        all_entries = get_symbols_cache().get()
    except Exception:
        logger.exception("list_futures_symbols: cache failed")
        return _error(ErrorCode.INTERNAL_ERROR.value, "symbol cache unavailable", status=500)

    if q:
        results = [
            e for e in all_entries
            if q in e.get("symbol", "").upper() or q in e.get("baseAsset", "").upper()
        ]
    else:
        results = all_entries

    return _success({
        "count": len(results),
        "results": results,
    })


@watchlist_bp.route("/admin/markets/futures/refresh", methods=["POST"])
@require_auth
def refresh_symbols_cache(user):
    """Force-refresh the symbol cache. Local-dev only (matches the existing
    admin gate pattern in the repo)."""
    if not _is_admin(user):
        return _error(ErrorCode.FORBIDDEN.value, "admin only", status=403)

    _, err = parse_request(WatchlistRefreshRequest, request.get_json(silent=True) or {})
    if err is not None:
        return err

    try:
        count = get_symbols_cache().refresh()
    except Exception:
        logger.exception("refresh_symbols_cache: refresh failed")
        return _error(ErrorCode.INTERNAL_ERROR.value, "refresh failed", status=500)
    return _success({"count": count})


def _is_admin(user: dict[str, Any]) -> bool:
    """Admin gate. In production this checks ``user.role == 'admin'``; in
    local-dev mode (DISABLE_AUTH=1) we trust the dev user unconditionally."""
    if is_local_dev_mode():
        return True
    return user.get("role") == "admin"


# ---------------------------------------------------------------------------
# Watchlist CRUD
# ---------------------------------------------------------------------------


@watchlist_bp.route("/watchlist", methods=["GET"])
@require_auth
def list_watchlist(user):
    items = _store().list_items(_user_id(user), DEFAULT_MARKET)
    return _success({"items": items, "limit": MAX_ITEMS_PER_USER})


@watchlist_bp.route("/watchlist", methods=["POST"])
@require_auth
def add_to_watchlist(user):
    req, err = parse_request(WatchlistAddRequest, request.get_json(silent=True))
    if err is not None:
        return err

    cache_entry = get_symbols_cache().get_meta(req.symbol)
    if cache_entry is None or cache_entry.get("quoteAsset") != "USDT":
        return _error(
            ErrorCode.INVALID_PARAMS.value,
            f"{req.symbol} is not a USDⓈ-M futures symbol",
            status=422,
        )

    try:
        meta = symbol_meta_from_cache(cache_entry)
        row = _store().create_item(_user_id(user), DEFAULT_MARKET, meta, note=req.note)
    except DuplicateError:
        return _error(
            ErrorCode.DUPLICATE_SYMBOL.value,
            f"{req.symbol} 已在自选中",
            status=409,
        )
    except LimitReachedError:
        return _error(
            ErrorCode.WATCHLIST_LIMIT_REACHED.value,
            f"自选最多 {MAX_ITEMS_PER_USER} 个，请先删除一些再添加",
            status=422,
        )
    except UnknownSymbolError:
        return _error(
            ErrorCode.WATCHLIST_UNKNOWN_SYMBOL.value,
            f"{req.symbol} 不在缓存的合约列表中",
            status=422,
        )
    except ValueError as exc:
        return _error(ErrorCode.INVALID_PARAMS.value, str(exc), status=422)
    return _success({"item": row})


@watchlist_bp.route("/watchlist/<item_id>", methods=["PATCH"])
@require_auth
def update_watchlist_item(user, item_id: str):
    req, err = parse_request(WatchlistUpdateRequest, request.get_json(silent=True))
    if err is not None:
        return err
    if req.note is None and req.sort_index is None:
        return _error(
            ErrorCode.INVALID_PARAMS.value,
            "request must include note or sort_index",
            status=422,
        )

    try:
        row = _store().update_item(
            item_id,
            _user_id(user),
            note=req.note,
            sort_index=req.sort_index,
        )
    except NotFoundError:
        return _error(ErrorCode.NOT_FOUND.value, "item not found", status=404)
    except ValueError as exc:
        return _error(ErrorCode.INVALID_PARAMS.value, str(exc), status=422)
    return _success({"item": row})


@watchlist_bp.route("/watchlist/<item_id>", methods=["DELETE"])
@require_auth
def delete_watchlist_item(user, item_id: str):
    try:
        _store().delete_item(item_id, _user_id(user))
    except NotFoundError:
        return _error(ErrorCode.NOT_FOUND.value, "item not found", status=404)
    return _success({"deleted": True, "id": item_id})


@watchlist_bp.route("/watchlist/reorder", methods=["POST"])
@require_auth
def reorder_watchlist(user):
    req, err = parse_request(WatchlistReorderRequest, request.get_json(silent=True))
    if err is not None:
        return err

    ordered_ids = [item.id for item in req.items]
    if len(set(ordered_ids)) != len(ordered_ids):
        return _error(
            ErrorCode.INVALID_PARAMS.value,
            "duplicate ids in reorder payload",
            status=422,
        )

    try:
        rows = _store().reorder(_user_id(user), DEFAULT_MARKET, ordered_ids)
    except NotFoundError as exc:
        return _error(ErrorCode.NOT_FOUND.value, str(exc), status=404)
    except ValueError as exc:
        return _error(ErrorCode.INVALID_PARAMS.value, str(exc), status=422)
    return _success({"items": rows})


# ---------------------------------------------------------------------------
# Internal helpers exposed for tests
# ---------------------------------------------------------------------------


def _build_store_with_cache(cache: FuturesSymbolsCache | None) -> WatchlistStore:
    """Test helper: build a store whose whitelist resolver consults ``cache``."""
    if cache is None:
        return WatchlistStore(whitelist_resolver=None)
    return WatchlistStore(whitelist_resolver=cache.get_meta)


# Re-export SymbolMeta so callers (and tests) can import everything from here.
__all__ = [
    "SymbolMeta",
    "WatchlistStore",
    "watchlist_bp",
    "_build_store_with_cache",
]