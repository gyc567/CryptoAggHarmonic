#!/usr/bin/env python3
"""Watchlist data-source verification script.

Run from the repo root (or worktree) to confirm that the data sources
the watchlist depends on are alive and contain the expected symbols.

Checks performed:
1. Local cache file (if present) contains MUUSDT, ORCLUSDT, AAPLUSDT,
   NVDAUSDT, TSLAUSDT, BTCUSDT.
2. Live ``GET https://fapi.binance.com/fapi/v1/exchangeInfo`` contains
   the same set of symbols with ``quoteAsset == "USDT"``.
3. Live ``GET /fapi/v1/premiumIndex?symbol=MUUSDT`` returns a numeric
   ``markPrice`` and ``fundingRate``.

Exits 0 on success, 1 on the first failure. Network failures are
flagged but do not crash the script — the local cache check still runs.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

FAPI_BASE = os.environ.get("BINANCE_FUTURES_REST_URL", "https://fapi.binance.com")
CACHE_PATH = Path(
    os.environ.get(
        "WATCHLIST_CACHE_PATH",
        str(Path(__file__).resolve().parent.parent / "app" / "cache" / "futures_symbols.json"),
    )
)

REQUIRED_USDT = {"MUUSDT", "ORCLUSDT", "AAPLUSDT", "NVDAUSDT", "TSLAUSDT", "BTCUSDT"}


def _fetch_json(url: str, timeout: float = 10.0) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "pyharmonics-watchlist-check/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — explicit URL
        return json.loads(resp.read().decode("utf-8"))


def check_local_cache() -> set[str]:
    print(f"[1/3] Local cache: {CACHE_PATH}")
    if not CACHE_PATH.exists():
        print("  ! cache file not found (run app/infra/futures_symbols_cache.py once)")
        return set()
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  FAIL: cannot parse cache: {exc}")
        return set()
    # Cache file is either a list of entries or ``{"symbols": [...]}``.
    if isinstance(raw, dict):
        entries = raw.get("symbols", [])
    elif isinstance(raw, list):
        entries = raw
    else:
        entries = []
    symbols = {entry.get("symbol") for entry in entries if isinstance(entry, dict)}
    missing = REQUIRED_USDT - symbols
    if missing:
        print(f"  FAIL: missing in cache: {sorted(missing)}")
        return set()
    print(f"  ok ({len(symbols)} symbols, includes {sorted(REQUIRED_USDT)})")
    return symbols


def check_exchange_info() -> set[str]:
    print(f"[2/3] Live {FAPI_BASE}/fapi/v1/exchangeInfo")
    try:
        body = _fetch_json(f"{FAPI_BASE}/fapi/v1/exchangeInfo")
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"  WARN: network/parse error: {exc}")
        return set()
    syms = body.get("symbols", []) if isinstance(body, dict) else []
    usdt = {
        s.get("symbol")
        for s in syms
        if isinstance(s, dict) and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
    }
    missing = REQUIRED_USDT - usdt
    if missing:
        print(f"  FAIL: USDⓈ-M missing {sorted(missing)}")
        return set()
    print(f"  ok ({len(usdt)} USDⓈ-M symbols)")
    return usdt


def check_premium_index(symbol: str = "MUUSDT") -> None:
    print(f"[3/3] Live /fapi/v1/premiumIndex?symbol={symbol}")
    url = f"{FAPI_BASE}/fapi/v1/premiumIndex?{urllib.parse.urlencode({'symbol': symbol})}"
    try:
        body = _fetch_json(url)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"  WARN: network/parse error: {exc}")
        return
    if not isinstance(body, dict):
        print(f"  FAIL: unexpected response type {type(body).__name__}")
        sys.exit(1)
    try:
        mark = float(body["markPrice"])
    except (KeyError, ValueError, TypeError) as exc:
        print(f"  FAIL: bad markPrice: {exc}")
        sys.exit(1)
    # Binance uses ``lastFundingRate`` in the premiumIndex payload (older
    # docs say ``fundingRate``). Accept either so the check survives
    # future renames.
    raw_rate = body.get("lastFundingRate", body.get("fundingRate"))
    try:
        funding = float(raw_rate) if raw_rate is not None else None
    except (ValueError, TypeError) as exc:
        print(f"  FAIL: bad funding rate: {exc}")
        sys.exit(1)
    print(f"  ok markPrice={mark} fundingRate={funding}")


def main() -> int:
    local = check_local_cache()
    live = check_exchange_info()
    check_premium_index()

    if not REQUIRED_USDT.issubset(local):
        print("\nFAILED: local cache incomplete.")
        return 1
    if not REQUIRED_USDT.issubset(live):
        print("\nFAILED: live exchangeInfo does not contain required USDⓈ-M symbols.")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())