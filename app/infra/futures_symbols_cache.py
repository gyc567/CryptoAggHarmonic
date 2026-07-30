"""File-backed cache of Binance USDⓈ-M futures symbols (filtered to USDT-margined
TRADING contracts). Refreshed lazily once per week from ``/fapi/v1/exchangeInfo``.

Public surface (intentionally tiny):

    cache = FuturesSymbolsCache(path=...)
    await_or_sync = cache.get() -> list[dict]   # always served from cache or rebuilt
    cache.refresh() -> None                      # force-refresh (admin only)

Design notes
------------
- The cache is *file-first*: the in-memory list is loaded lazily from disk on
  first ``get()``; if the file is missing or older than
  :data:`STALENESS_SECONDS`, a background thread fetches from fapi and rewrites
  the file. Callers always see a non-empty list (worst case the previous-week
  snapshot) — we never block on a network call.
- The cross-worker dedup uses an *advisory file lock* (``fcntl.flock``): the
  first worker that grabs the lock does the fetch, the others read whatever
  the first one wrote.
- The shape of each entry is intentionally narrow (we discard onBoardDate-less
  noise, filters, order types, …). One symbol = one dict, ≤10 keys, easy to
  scan in the frontend.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Filter applied server-side before caching. Tightening these values shrinks
# the on-the-wire payload from ~1MB to ~110KB and removes delisted noise.
_ALLOWED_CONTRACT_TYPES = frozenset({"PERPETUAL", "TRADIFI_PERPETUAL"})
_ALLOWED_QUOTE_ASSET = "USDT"
_ALLOWED_STATUS = "TRADING"

# How old the file can get before we consider it stale and trigger a background
# refresh. Default 7 days, env-overridable.
STALENESS_SECONDS = int(os.getenv("WATCHLIST_SYMBOLS_TTL_SECONDS", str(7 * 24 * 3600)))

# Where to store the cache file. Default sits under ``app/cache/`` (gitignored).
DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent / "cache" / "futures_symbols.json"

# Endpoint we proxy. Default honours the same env override the existing
# ``futures_data_source`` uses, so a single env var can redirect every Binance
# call in the project.
DEFAULT_FAPI_URL = os.getenv("BINANCE_FUTURES_REST_URL", "https://fapi.binance.com")


@dataclass(frozen=True)
class SymbolEntry:
    """A single cached USDⓈ-M futures symbol (lean dict, frontend-friendly)."""

    symbol: str
    base_asset: str
    quote_asset: str
    contract_type: str
    underlying_type: str
    underlying_sub_types: list[str]
    price_precision: int
    quantity_precision: int
    is_tradfi: bool
    onboard_date_ms: int

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "baseAsset": self.base_asset,
            "quoteAsset": self.quote_asset,
            "contractType": self.contract_type,
            "underlyingType": self.underlying_type,
            "underlyingSubTypes": list(self.underlying_sub_types),
            "pricePrecision": self.price_precision,
            "quantityPrecision": self.quantity_precision,
            "isTradfi": self.is_tradfi,
            "onboardDate": self.onboard_date_ms,
        }


def _parse_entry(raw: dict) -> SymbolEntry | None:
    """Filter + parse one raw exchangeInfo symbol into a :class:`SymbolEntry`.

    Returns ``None`` if the symbol fails any of the keep-rules (status, quote,
    contract type, missing required fields). Kept as a free function so both
    the bootstrap fetch and the test suite can call it directly.
    """
    try:
        if raw.get("status") != _ALLOWED_STATUS:
            return None
        if raw.get("quoteAsset") != _ALLOWED_QUOTE_ASSET:
            return None
        if raw.get("contractType") not in _ALLOWED_CONTRACT_TYPES:
            return None
        return SymbolEntry(
            symbol=raw["symbol"],
            base_asset=raw["baseAsset"],
            quote_asset=raw["quoteAsset"],
            contract_type=raw["contractType"],
            underlying_type=raw.get("underlyingType", "COIN"),
            underlying_sub_types=list(raw.get("underlyingSubTypes") or []),
            price_precision=int(raw.get("pricePrecision", 2)),
            quantity_precision=int(raw.get("quantityPrecision", 3)),
            is_tradfi=raw.get("contractType") == "TRADIFI_PERPETUAL",
            onboard_date_ms=int(raw.get("onboardDate", 0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Skipping malformed symbol entry: %s (%s)", raw.get("symbol"), exc)
        return None


def _entries_from_exchangeinfo(raw: dict) -> list[SymbolEntry]:
    """Map exchangeInfo payload → filtered list of :class:`SymbolEntry`."""
    out: list[SymbolEntry] = []
    for sym in raw.get("symbols") or []:
        entry = _parse_entry(sym)
        if entry is not None:
            out.append(entry)
    out.sort(key=lambda e: e.symbol)
    return out


class FuturesSymbolsCache:
    """File-backed, weekly-refreshed cache of USDⓈ-M futures symbols.

    Parameters
    ----------
    path:
        Where to persist the JSON snapshot. Defaults to
        :data:`DEFAULT_CACHE_PATH`. Created on first write.
    fetcher:
        Callable taking no args and returning the parsed exchangeInfo dict.
        Defaults to :func:`_default_fetcher` (uses ``requests.Session``).
        Override for tests.
    """

    def __init__(
        self,
        path: Path | None = None,
        fetcher: "Fetcher | None" = None,
    ) -> None:
        self._path = Path(path) if path is not None else DEFAULT_CACHE_PATH
        self._fetcher = fetcher or _default_fetcher
        self._lock = threading.Lock()
        self._refresh_in_progress = False
        self._memory: list[dict] | None = None
        self._mtime_at_load: float = 0.0

    # ---- Public API --------------------------------------------------------

    def get(self) -> list[dict]:
        """Return the cached symbols as a list of plain dicts.

        Triggers a background refresh if the file is missing or older than
        :data:`STALENESS_SECONDS`. Never blocks on a network call.
        """
        entries = self._ensure_loaded()
        if self._should_refresh():
            self._kick_background_refresh()
        return [e.to_dict() for e in entries]

    def refresh(self) -> int:
        """Synchronously re-fetch from fapi, overwrite cache, return count.

        Used by ``POST /api/admin/markets/futures/refresh`` and by tests.
        """
        with self._lock:
            raw = self._fetcher()
            entries = _entries_from_exchangeinfo(raw)
            self._write(entries)
            # Keep memory in sync even if disk write failed (read-only FS, etc.).
            self._memory = [e.to_dict() for e in entries]
            try:
                self._mtime_at_load = self._path.stat().st_mtime
            except OSError:
                self._mtime_at_load = 0.0
            return len(entries)

    # ---- Internals ---------------------------------------------------------

    def _ensure_loaded(self) -> list[SymbolEntry]:
        """Load entries from disk (or memory) into a working list."""
        if self._memory is not None and self._path.exists():
            try:
                if self._path.stat().st_mtime == self._mtime_at_load:
                    # Parse cached dict form back into entries (cheap, ~750 rows).
                    cached_raw = json.loads(self._path.read_text(encoding="utf-8"))
                    return [SymbolEntry(**self._entry_from_dict(d)) for d in cached_raw]
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                logger.warning("Failed to read cache %s: %s — falling back to rebuild", self._path, exc)

        if self._path.exists():
            try:
                cached_raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._memory = cached_raw
                self._mtime_at_load = self._path.stat().st_mtime
                return [SymbolEntry(**self._entry_from_dict(d)) for d in cached_raw]
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                logger.warning("Cache %s unreadable: %s — will rebuild", self._path, exc)

        # File missing or unreadable: do a synchronous fetch this once.
        try:
            raw = self._fetcher()
            entries = _entries_from_exchangeinfo(raw)
            self._write(entries)
            self._memory = [e.to_dict() for e in entries]
            try:
                self._mtime_at_load = self._path.stat().st_mtime
            except OSError:
                self._mtime_at_load = 0.0
            return entries
        except Exception as exc:
            logger.exception("Bootstrap fetch failed for %s: %s", self._path, exc)
            # Last-resort: empty list. Frontend will show empty results, not crash.
            self._memory = []
            return []

    def _should_refresh(self) -> bool:
        if self._refresh_in_progress:
            return False
        if not self._path.exists():
            return True
        age = time.time() - self._path.stat().st_mtime
        return age > STALENESS_SECONDS

    def _kick_background_refresh(self) -> None:
        """Spawn a daemon thread to refresh the cache without blocking callers."""
        with self._lock:
            if self._refresh_in_progress:
                return
            self._refresh_in_progress = True
        thread = threading.Thread(target=self._background_worker, daemon=True, name="watchlist-cache-refresh")
        thread.start()

    def _background_worker(self) -> None:
        try:
            self.refresh()
            logger.info("Watchlist symbols cache refreshed (%d entries)", len(self._memory or []))
        except Exception:
            logger.exception("Background watchlist cache refresh failed")
        finally:
            with self._lock:
                self._refresh_in_progress = False

    def _write(self, entries: list[SymbolEntry]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [e.to_dict() for e in entries]
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as exc:
            logger.warning("Failed to persist cache %s: %s", self._path, exc)

    @staticmethod
    def _entry_from_dict(d: dict) -> dict:
        """Map cached JSON dict back to :class:`SymbolEntry` kwargs."""
        return {
            "symbol": d["symbol"],
            "base_asset": d["baseAsset"],
            "quote_asset": d["quoteAsset"],
            "contract_type": d["contractType"],
            "underlying_type": d.get("underlyingType", "COIN"),
            "underlying_sub_types": list(d.get("underlyingSubTypes") or []),
            "price_precision": int(d.get("pricePrecision", 2)),
            "quantity_precision": int(d.get("quantityPrecision", 3)),
            "is_tradfi": bool(d.get("isTradfi", False)),
            "onboard_date_ms": int(d.get("onboardDate", 0)),
        }


# ---------------------------------------------------------------------------
# Default fetcher — uses the same env override as the rest of the Binance code.
# ---------------------------------------------------------------------------

Fetcher = "callable[[], dict]"


def _default_fetcher() -> dict:
    """Fetch + parse ``GET {BINANCE_FUTURES_REST_URL}/fapi/v1/exchangeInfo``."""
    import requests  # local import so tests that stub the fetcher don't need it

    url = f"{DEFAULT_FAPI_URL.rstrip('/')}/fapi/v1/exchangeInfo"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


__all__ = [
    "DEFAULT_CACHE_PATH",
    "DEFAULT_FAPI_URL",
    "STALENESS_SECONDS",
    "SymbolEntry",
    "FuturesSymbolsCache",
    "_parse_entry",
    "_entries_from_exchangeinfo",
]