"""binance market data → HISTORY.jsonl handshake (Loop #12).

Persists market data observations to the project's HISTORY.jsonl so
the loop-engineering pipeline can correlate market context with
candidate proposals.

Schema (one JSON object per line):

  {
    "source": "binance_market",
    "endpoint": "mark_price" | "open_interest" | "funding_history",
    "symbol": "BTCUSDT",
    "ts": 1786545458,
    "latency_ms": 720,
    "payload": {...}            # endpoint-specific
    "salt_version": 1
  }

Append-only, like the OKX / freqtrade paths. Uses the project's
``state.append_history`` helper from ``app/loop/state.py`` so the
file lock and rotation policy are inherited.

ADR-0013 D5: ``source: binance_market`` exempt from
``freqtrade_hyperopt`` ↔ ``okx_*``互斥 (read-only).

ponytail: minimum viable. No batching, no cache, no TTL — one fetch
maps to one history line. Aggregation is a future concern.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

SOURCE_TAG: str = "binance_market"
SALT_VERSION: int = 1


@dataclass(frozen=True)
class HistoryEntry:
    """One market-data observation, ready to be appended to HISTORY.jsonl."""

    source: str
    endpoint: str
    symbol: str
    ts: int
    latency_ms: int
    payload: dict[str, Any]
    salt_version: int = SALT_VERSION


def _to_entry(
    endpoint: str,
    symbol: str,
    payload: dict[str, Any],
    latency_ms: int,
    ts: int | None = None,
) -> HistoryEntry:
    """Build a HistoryEntry from endpoint name + symbol + parsed payload."""
    return HistoryEntry(
        source=SOURCE_TAG,
        endpoint=endpoint,
        symbol=symbol,
        ts=ts if ts is not None else int(time.time()),
        latency_ms=int(latency_ms),
        payload=payload,
        salt_version=SALT_VERSION,
    )


def record_mark_price(
    mark_price: Any,
    *,
    latency_ms: int,
    ts: int | None = None,
) -> HistoryEntry:
    """Convert a MarkPrice dataclass into a history entry."""
    payload = asdict(mark_price)
    return _to_entry("mark_price", mark_price.symbol, payload, latency_ms, ts)


def record_open_interest(
    open_interest: Any,
    *,
    latency_ms: int,
    ts: int | None = None,
) -> HistoryEntry:
    """Convert an OpenInterest dataclass into a history entry."""
    payload = asdict(open_interest)
    return _to_entry("open_interest", open_interest.symbol, payload, latency_ms, ts)


def record_funding_history(
    funding_rates: list[Any],
    *,
    symbol: str,
    latency_ms: int,
    ts: int | None = None,
) -> HistoryEntry:
    """Convert a list of FundingRate dataclasses into a history entry."""
    payload = {
        "symbol": symbol,
        "entries": [asdict(fr) for fr in funding_rates],
        "count": len(funding_rates),
    }
    return _to_entry("funding_history", symbol, payload, latency_ms, ts)


def append(entry: HistoryEntry, root=None) -> None:
    """Append ``entry`` to HISTORY.jsonl via ``state.append_history``.

    The state helper handles file lock + rotation. We never write the
    file directly here, so the durability guarantees of the loop
    pipeline apply uniformly.

    ``root`` is forwarded to ``state.append_history``; defaults to
    ``.scratch/loop_state`` (the project's loop-engineering root).
    Tests pass a tmp_path so the live file is never touched.
    """
    # Imported lazily so the binance package has zero hard dependency
    # on ``app.loop.state`` at module-import time. This keeps the
    # package importable in lightweight contexts (e.g. the CLI smoke
    # script we ran in [binance-cli-install-01]).
    from app.loop.state import append_history  # noqa: PLC0415

    record = {
        "source": entry.source,
        "endpoint": entry.endpoint,
        "symbol": entry.symbol,
        "ts": entry.ts,
        "latency_ms": entry.latency_ms,
        "payload": entry.payload,
        "salt_version": entry.salt_version,
    }
    try:
        if root is not None:
            append_history(record, root=root)
        else:
            append_history(record)
    except Exception as e:  # pragma: no cover — defensive; append_history has its own tests
        logger.warning(
            "binance handshake: failed to append %s/%s entry: %s",
            entry.endpoint,
            entry.symbol,
            e,
        )