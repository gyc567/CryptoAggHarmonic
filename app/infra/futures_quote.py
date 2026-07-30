"""Binance USDT-M Futures batch quote helper.

The watchlist page needs the same handful of live fields for every symbol a
user has starred. To avoid one HTTP round-trip per row we call the two
list endpoints once and merge them server-side:

* ``GET /fapi/v1/ticker/24hr``         — lastPrice / priceChangePercent /
  volume / quoteVolume / count / highPrice / lowPrice (per symbol).
* ``GET /fapi/v1/premiumIndex``        — markPrice / fundingRate /
  nextFundingTime (per symbol).

Both endpoints return the full list with no symbol parameter, so we can
return up to ~100 symbols in a single round-trip. The helper exposes:

* :func:`fetch_quotes`        — public API; takes a list of symbols and
  returns ``{symbol: FuturesQuote}``.
* :class:`QuoteFetchError`    — raised on hard transport failure after
  retries are exhausted (HTTP 4xx other than 429 is *not* retried).
* :func:`parse_quotes_payload` — pure function used by tests to assemble a
  ``dict[symbol, FuturesQuote]`` from two JSON payloads.

429 / network failures are retried with exponential backoff
(0.5s → 1s → 2s, then re-raise). The cap is intentionally tight because
the route handler runs in the request thread; a long backoff would
block the Flask worker.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

DEFAULT_FAPI_BASE = "https://fapi.binance.com"
TICKER_24HR_PATH = "/fapi/v1/ticker/24hr"
PREMIUM_INDEX_PATH = "/fapi/v1/premiumIndex"

# Per-symbol 24hr fields we care about (subset of Binance payload).
TICKER_FIELDS = (
    "lastPrice",
    "priceChangePercent",
    "volume",
    "quoteVolume",
    "count",
    "highPrice",
    "lowPrice",
)

# Per-symbol premiumIndex fields we care about.
PREMIUM_FIELDS = (
    "markPrice",
    "fundingRate",
    "nextFundingTime",
)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FuturesQuote:
    """A merged 24hr + premiumIndex snapshot for a single symbol."""

    symbol: str
    last_price: float | None = None
    price_change_percent: float | None = None
    mark_price: float | None = None
    funding_rate: float | None = None
    next_funding_time: int | None = None
    high_price: float | None = None
    low_price: float | None = None
    volume: float | None = None
    quote_volume: float | None = None
    count: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict (omit null fields)."""
        out: dict[str, Any] = {"symbol": self.symbol}
        for src_key, dst_key in (
            ("last_price", "lastPrice"),
            ("price_change_percent", "priceChangePercent"),
            ("mark_price", "markPrice"),
            ("funding_rate", "fundingRate"),
            ("next_funding_time", "nextFundingTime"),
            ("high_price", "highPrice"),
            ("low_price", "lowPrice"),
            ("volume", "volume"),
            ("quote_volume", "quoteVolume"),
            ("count", "count"),
        ):
            v = getattr(self, src_key)
            if v is not None:
                out[dst_key] = v
        if self.extra:
            out["extra"] = dict(self.extra)
        return out


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class QuoteFetchError(RuntimeError):
    """Raised when the upstream quote endpoint cannot be reached after retries."""


# ---------------------------------------------------------------------------
# Pure helpers (easy to unit-test)
# ---------------------------------------------------------------------------


def normalize_symbol(raw: str) -> str:
    """Normalize a single symbol for matching against the upstream payloads.

    Binance is case-insensitive and rejects empty strings.
    """
    if not isinstance(raw, str):
        raise ValueError(f"symbol must be str, got {type(raw).__name__}")
    s = raw.strip().upper()
    if not s:
        raise ValueError("symbol cannot be empty")
    return s


def filter_known_symbols(
    symbols: Iterable[str],
    *,
    whitelist: Iterable[str] | None,
) -> tuple[list[str], list[str]]:
    """Split a raw symbol list into ``(known, unknown)``.

    Used by the route to surface unknown symbols to the caller while still
    returning quotes for the known ones. Whitespace, casing, and duplicates
    are normalized.
    """
    if whitelist is None:
        return sorted({normalize_symbol(s) for s in symbols}), []
    allowed = {s.upper() for s in whitelist}
    seen: set[str] = set()
    known: list[str] = []
    unknown: list[str] = []
    for raw in symbols:
        try:
            norm = normalize_symbol(raw)
        except ValueError:
            unknown.append(raw)
            continue
        if norm in allowed:
            if norm not in seen:
                seen.add(norm)
                known.append(norm)
        else:
            unknown.append(norm)
    return known, unknown


def parse_quotes_payload(
    *,
    symbols: Iterable[str],
    ticker_payload: Iterable[Mapping[str, Any]] | None,
    premium_payload: Iterable[Mapping[str, Any]] | None,
) -> dict[str, FuturesQuote]:
    """Merge the two upstream JSON payloads into a ``{symbol: FuturesQuote}`` map.

    Symbols present in only one of the payloads still get a row (the
    missing side defaults to ``None``). Symbols requested but missing
    from both payloads get an entry with everything ``None`` so the UI
    can render a "delisted" placeholder.
    """
    norm_syms = [normalize_symbol(s) for s in symbols]
    by_symbol: dict[str, FuturesQuote] = {
        s: FuturesQuote(symbol=s) for s in norm_syms
    }

    if ticker_payload is not None:
        for row in ticker_payload:
            sym_raw = row.get("symbol")
            if not isinstance(sym_raw, str):
                continue
            sym = sym_raw.upper()
            if sym not in by_symbol:
                continue
            quote = by_symbol[sym]
            by_symbol[sym] = _apply(quote, _coerce_ticker(row, quote))

    if premium_payload is not None:
        for row in premium_payload:
            sym_raw = row.get("symbol")
            if not isinstance(sym_raw, str):
                continue
            sym = sym_raw.upper()
            if sym not in by_symbol:
                continue
            quote = by_symbol[sym]
            by_symbol[sym] = _apply(quote, _coerce_premium(row, quote))

    return by_symbol


def _coerce_ticker(
    row: Mapping[str, Any],
    existing: FuturesQuote,
) -> dict[str, Any]:
    """Extract ticker fields from a Binance row, leaving None on parse failure."""
    out: dict[str, Any] = {
        "last_price": _as_float(row.get("lastPrice"), existing.last_price),
        "price_change_percent": _as_float(
            row.get("priceChangePercent"), existing.price_change_percent
        ),
        "high_price": _as_float(row.get("highPrice"), existing.high_price),
        "low_price": _as_float(row.get("lowPrice"), existing.low_price),
        "volume": _as_float(row.get("volume"), existing.volume),
        "quote_volume": _as_float(row.get("quoteVolume"), existing.quote_volume),
        "count": _as_int(row.get("count"), existing.count),
    }
    return out


def _coerce_premium(
    row: Mapping[str, Any],
    existing: FuturesQuote,
) -> dict[str, Any]:
    return {
        "mark_price": _as_float(row.get("markPrice"), existing.mark_price),
        "funding_rate": _as_float(row.get("fundingRate"), existing.funding_rate),
        "next_funding_time": _as_int(
            row.get("nextFundingTime"), existing.next_funding_time
        ),
    }


def _apply(
    existing: FuturesQuote,
    patch: dict[str, Any],
) -> FuturesQuote:
    """Build a new FuturesQuote from ``existing`` with ``patch`` fields replaced.

    Keeping it immutable (per the dataclass) — the route should treat the
    result as read-only.
    """
    base = {
        "symbol": existing.symbol,
        "last_price": existing.last_price,
        "price_change_percent": existing.price_change_percent,
        "mark_price": existing.mark_price,
        "funding_rate": existing.funding_rate,
        "next_funding_time": existing.next_funding_time,
        "high_price": existing.high_price,
        "low_price": existing.low_price,
        "volume": existing.volume,
        "quote_volume": existing.quote_volume,
        "count": existing.count,
        "extra": existing.extra,
    }
    base.update(patch)
    return FuturesQuote(**base)


def _as_float(value: Any, fallback: float | None) -> float | None:
    if value is None:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int(value: Any, fallback: int | None) -> int | None:
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


# ---------------------------------------------------------------------------
# Live fetcher
# ---------------------------------------------------------------------------


def fetch_quotes(
    symbols: Iterable[str],
    *,
    whitelist: Iterable[str] | None = None,
    base_url: str = DEFAULT_FAPI_BASE,
    session: requests.Session | None = None,
    timeout: float = 8.0,
    max_retries: int = 3,
    backoff: float = 0.5,
    sleep: Any = time.sleep,
) -> dict[str, FuturesQuote]:
    """Fetch live 24hr + premiumIndex quotes for ``symbols``.

    Returns a ``{symbol: FuturesQuote}`` map containing only the symbols
    that are in ``whitelist`` (if provided). Unknown symbols are silently
    dropped; the caller should call :func:`filter_known_symbols` first if
    it wants to surface them.

    Retries: on HTTP 429 or ``requests.ConnectionError``/``Timeout``,
    sleep ``backoff * 2**attempt`` and try again, up to ``max_retries``
    total. Other HTTP errors and ``ValueError`` from upstream payloads
    are *not* retried — they indicate a structural problem with the
    response that won't fix itself.
    """
    known, _unknown = filter_known_symbols(symbols, whitelist=whitelist)
    if not known:
        return {}

    owned_session = session is None
    sess = session or requests.Session()
    sess.headers.setdefault("User-Agent", "pyharmonics-gpt/1.0")
    sess.headers.setdefault("Accept", "application/json")

    try:
        ticker_payload = _get_with_retry(
            sess, base_url, TICKER_24HR_PATH, timeout, max_retries, backoff, sleep
        )
        premium_payload = _get_with_retry(
            sess, base_url, PREMIUM_INDEX_PATH, timeout, max_retries, backoff, sleep
        )
    finally:
        if owned_session:
            sess.close()

    return parse_quotes_payload(
        symbols=known,
        ticker_payload=ticker_payload,
        premium_payload=premium_payload,
    )


def _get_with_retry(
    session: requests.Session,
    base_url: str,
    path: str,
    timeout: float,
    max_retries: int,
    backoff: float,
    sleep: Any,
) -> list[Any]:
    """GET ``base_url+path`` with retry on 429 / network errors."""
    url = f"{base_url}{path}"
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = session.get(url, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            _backoff_sleep(sleep, backoff, attempt)
            continue
        if resp.status_code == 429:
            last_exc = QuoteFetchError(f"{path}: HTTP 429 rate-limited")
            _backoff_sleep(sleep, backoff, attempt)
            continue
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            # Hard error: don't retry, but stash so the caller can see.
            raise QuoteFetchError(f"{path}: HTTP {resp.status_code}") from exc
        try:
            return resp.json()
        except ValueError as exc:
            last_exc = QuoteFetchError(f"{path}: invalid JSON ({exc})")
            # Bad JSON won't fix itself; don't retry.
            break
    raise QuoteFetchError(f"{path}: gave up after {max_retries} attempts: {last_exc}")


def _backoff_sleep(sleep: Any, backoff: float, attempt: int) -> None:
    try:
        sleep(backoff * (2 ** attempt))
    except Exception:  # pragma: no cover — sleep shouldn't fail
        pass


# ---------------------------------------------------------------------------
# Module-level guard against concurrent fetches in the same process
# ---------------------------------------------------------------------------


_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT: set[str] = set()


def claim_fetch(origin: str) -> bool:
    """Reserve ``origin`` as in-flight; returns False if already running.

    A simple de-dupe so two Flask workers don't hammer Binance on the
    same client refresh.
    """
    with _INFLIGHT_LOCK:
        if origin in _INFLIGHT:
            return False
        _INFLIGHT.add(origin)
        return True


def release_fetch(origin: str) -> None:
    with _INFLIGHT_LOCK:
        _INFLIGHT.discard(origin)


__all__ = [
    "DEFAULT_FAPI_BASE",
    "FuturesQuote",
    "QuoteFetchError",
    "claim_fetch",
    "fetch_quotes",
    "filter_known_symbols",
    "normalize_symbol",
    "parse_quotes_payload",
    "release_fetch",
]