"""binance market data — Flask routes (Loop #12 Phase 2).

Exposes the ``app.services.binance.data_source`` wrapper as 3 read-only
endpoints under ``/api/binance/``. Each route:

  1. Validates the symbol (no auth — public market data)
  2. Calls the wrapper and records latency + status
  3. Emits the Prometheus metrics via ``record_binance_market_fetch``
  4. Optionally appends a HISTORY.jsonl entry via ``handshake.append``

Per ADR-0013 D1: read-only complement to ``app/infra/marketdata.py``.
The endpoints are designed to be **side-effect-free** by default; the
``persistence`` query param (``true`` / ``false``) controls whether
the observation is logged to HISTORY.jsonl.

End-to-end history:

  - 2025-08-12: Phase 1 implementation (data_source, handshake, metrics)
  - 2025-08-12: Phase 2 routes — this file
  - Future: Phase 3 outerloop correlation (candidate Sharpe ↔ funding regime)
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any

from flask import Blueprint, jsonify, request

from app.services.binance.data_source import (
    BinanceCliError,
    fetch_funding_history,
    fetch_mark_price,
    fetch_open_interest,
)

logger = logging.getLogger(__name__)


def make_binance_blueprint() -> Blueprint:
    """Build the read-only Binance market data blueprint.

    Endpoints:
      - GET /api/binance/mark-price?symbol=BTCUSDT
      - GET /api/binance/open-interest?symbol=BTCUSDT
      - GET /api/binance/funding-history?symbol=BTCUSDT&limit=10
      - GET /api/binance/capabilities       (self-describing)

    All market endpoints accept ``?persistence=true`` to append a
    HISTORY.jsonl row. Default is ``false`` (the wrapper is fast and
    idempotent; the route handler is the common case).
    """
    bp = Blueprint("binance", __name__, url_prefix="/api/binance")

    @bp.route("/mark-price")
    def mark_price():
        return _handle_endpoint("mark_price", _fetch_mark_price_handler)

    @bp.route("/open-interest")
    def open_interest():
        return _handle_endpoint("open_interest", _fetch_open_interest_handler)

    @bp.route("/funding-history")
    def funding_history():
        return _handle_endpoint(
            "funding_history", _fetch_funding_history_handler
        )

    @bp.route("/capabilities")
    def capabilities():
        """Self-describing endpoint — matches FT Strategy Loop's pattern."""
        return jsonify(
            {
                "endpoints": [
                    {
                        "path": "/api/binance/mark-price",
                        "method": "GET",
                        "params": ["symbol", "persistence?"],
                        "returns": "MarkPrice",
                    },
                    {
                        "path": "/api/binance/open-interest",
                        "method": "GET",
                        "params": ["symbol", "persistence?"],
                        "returns": "OpenInterest",
                    },
                    {
                        "path": "/api/binance/funding-history",
                        "method": "GET",
                        "params": ["symbol", "limit?", "persistence?"],
                        "returns": "list[FundingRate]",
                    },
                ],
                "loop": "Binance Market Data Loop (#12)",
                "source": "binance-cli (@binance/binance-cli v1.3.0)",
                "auth": "none (public market data)",
                "adr": "0013",
            }
        )

    return bp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_symbol(s: str) -> bool:
    """Symbols are uppercase alphanumerics; optionally ending 'USDT'.

    The wrapper itself handles invalid symbols by raising BinanceCliError,
    but this quick check lets us return 400 (bad request) instead of 502
    (bad gateway) for the common typo case.
    """
    if not isinstance(s, str):
        return False
    s = s.strip().upper()
    return 5 <= len(s) <= 20 and s.replace("/", "").replace(":", "").isalnum()


def _persistence_requested() -> bool:
    """Return True if the caller wants a HISTORY.jsonl entry appended."""
    val = request.args.get("persistence", "false").lower()
    return val in ("true", "1", "yes")


def _record_metric(endpoint: str, status: str, latency_s: float) -> None:
    """Forward to the prometheus metrics registry (no-op if missing)."""
    try:
        from app.api.metrics_routes import record_binance_market_fetch
        record_binance_market_fetch(endpoint, status, latency_s)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("metrics emit failed for %s: %s", endpoint, e)


def _maybe_persist(
    endpoint: str,
    symbol: str,
    payload: Any,
    latency_s: float,
) -> None:
    """Append to HISTORY.jsonl if the caller opted in."""
    if not _persistence_requested():
        return
    try:
        from app.services.binance.handshake import (
            record_funding_history,
            record_mark_price,
            record_open_interest,
            append,
        )
        latency_ms = int(latency_s * 1000)
        if endpoint == "mark_price":
            from app.services.binance.data_source import MarkPrice

            # Reconstruct a MarkPrice from the response payload.
            entry = record_mark_price(
                MarkPrice(
                    symbol=payload["symbol"],
                    mark_price=payload["mark_price"],
                    index_price=payload["index_price"],
                    estimated_settle_price=payload["estimated_settle_price"],
                    last_funding_rate=payload["last_funding_rate"],
                    next_funding_time=payload["next_funding_time"],
                    time=payload["time"],
                ),
                latency_ms=latency_ms,
            )
        elif endpoint == "open_interest":
            from app.services.binance.data_source import OpenInterest

            entry = record_open_interest(
                OpenInterest(
                    symbol=payload["symbol"],
                    open_interest=payload["open_interest"],
                    time=payload["time"],
                ),
                latency_ms=latency_ms,
            )
        elif endpoint == "funding_history":
            from app.services.binance.data_source import FundingRate

            rates = [
                FundingRate(
                    symbol=item["symbol"],
                    funding_time=item["funding_time"],
                    funding_rate=item["funding_rate"],
                    mark_price=item["mark_price"],
                )
                for item in payload["entries"]
            ]
            entry = record_funding_history(
                rates,
                symbol=payload["symbol"],
                latency_ms=latency_ms,
            )
        else:
            logger.warning("unknown endpoint %s in _maybe_persist", endpoint)
            return
        append(entry)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("HISTORY.jsonl append failed for %s: %s", endpoint, e)


def _handle_endpoint(endpoint: str, handler):
    """Common boilerplate: symbol validation, timing, metric, persistence."""
    symbol = request.args.get("symbol", "").strip().upper()
    if not _valid_symbol(symbol):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "invalid_symbol",
                    "message": f"symbol {symbol!r} failed validation",
                }
            ),
            400,
        )

    t0 = time.perf_counter()
    try:
        result = handler(symbol)
    except BinanceCliError as e:
        elapsed = time.perf_counter() - t0
        # Classify: timeout vs other CLI errors
        status = "timeout" if "timed out" in str(e) else "cli_error"
        _record_metric(endpoint, status, elapsed)
        return (
            jsonify(
                {
                    "success": False,
                    "error": status,
                    "message": str(e),
                    "symbol": symbol,
                    "latency_ms": int(elapsed * 1000),
                }
            ),
            502,  # Bad Gateway — upstream of Flask failed
        )
    except Exception as e:  # pragma: no cover — defensive
        elapsed = time.perf_counter() - t0
        _record_metric(endpoint, "json_error", elapsed)
        logger.exception("binance %s unexpected error", endpoint)
        return (
            jsonify(
                {
                    "success": False,
                    "error": "internal_error",
                    "message": str(e),
                }
            ),
            500,
        )

    elapsed = time.perf_counter() - t0
    payload = asdict(result) if hasattr(result, "__dataclass_fields__") else result
    _record_metric(endpoint, "ok", elapsed)
    _maybe_persist(endpoint, symbol, payload, elapsed)
    return jsonify(
        {
            "success": True,
            "endpoint": endpoint,
            "symbol": symbol,
            "latency_ms": int(elapsed * 1000),
            "data": payload,
            "persisted": _persistence_requested(),
        }
    )


# ---------------------------------------------------------------------------
# Endpoint wrappers (testable in isolation)
# ---------------------------------------------------------------------------


def _fetch_mark_price_handler(symbol: str):
    return fetch_mark_price(symbol)


def _fetch_open_interest_handler(symbol: str):
    return fetch_open_interest(symbol)


def _fetch_funding_history_handler(symbol: str):
    # Read limit from query params (default 10, max 100)
    limit_str = request.args.get("limit", "10")
    try:
        limit = int(limit_str)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(100, limit))
    return fetch_funding_history(symbol, limit=limit)