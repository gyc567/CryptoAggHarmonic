"""binance market data source — Loop #12 read-only adapter.

Wraps ``binance-cli`` (npm package ``@binance/binance-cli``, installed at
``/Users/jie/.hermes/node/bin/binance-cli``) so callers can fetch:

  - mark price + funding rate (via ``futures-usds mark-price``)
  - open interest (via ``futures-usds open-interest``)
  - funding rate history (via ``futures-usds get-funding-rate-history``)

without shelling out to the CLI themselves. Output is normalised to
plain Python dicts with stable types (``str → float`` conversions
applied; ``time`` fields left as ``int`` ms epoch).

Per ADR-0013 (D1–D6):

  - D1: read-only complement to ``app/infra/marketdata.py``; never
    replaces it. The 200 OK REST path stays as the primary fallback.
  - D2: Phase 1 scope = market data only. No write tool ever invoked
    from this module.
  - D3: subprocess invocation uses ``shell=False`` + argv list (no
    string injection). Errors raised are typed (``BinanceCliError``).
  - D4: profile / API key comes from env vars
    (``BINANCE_API_KEY`` / ``BINANCE_SECRET_KEY``), never from args.
    Public market data endpoints don't require a key; the wrapper
    passes none.
  - D5: 1 second timeout per call (CLI startup + REST roundtrip
    comfortably under 1s on warm cache). Caller may override.
  - D6: ``metrics.py`` records ``binance_market_fetch_total`` (counter,
    by endpoint + status) and ``binance_market_latency_seconds``
    (histogram).
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: Path to the binance-cli binary. Resolved at import time; override
#: with ``BINANCE_CLI_BIN`` env var if you ship a different binary.
import os as _os
BINANCE_CLI_BIN: str = _os.environ.get("BINANCE_CLI_BIN", "binance-cli")

#: Default per-call timeout. The CLI process spawns node + connects to
#: REST; 5 s is the high-water mark we observed on direct REST.
DEFAULT_TIMEOUT_S: float = 5.0


class BinanceCliError(RuntimeError):
    """Raised when a binance-cli invocation fails (non-zero exit, malformed JSON, timeout)."""


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FundingRate:
    """One funding rate observation for a symbol at a point in time."""

    symbol: str
    funding_time: int          # unix ms
    funding_rate: float
    mark_price: float | None  # may be absent on history entries
    rate_type: str = "Regular"


@dataclass(frozen=True)
class OpenInterest:
    """Current open interest snapshot for a symbol."""

    symbol: str
    open_interest: float       # in base asset units (e.g. BTC for BTCUSDT)
    time: int                  # unix ms


@dataclass(frozen=True)
class MarkPrice:
    """Mark price + index price + funding snapshot."""

    symbol: str
    mark_price: float
    index_price: float
    estimated_settle_price: float | None
    last_funding_rate: float
    next_funding_time: int
    time: int


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


def _run_cli(argv: list[str], timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    """Invoke binance-cli and return stdout. Raise ``BinanceCliError`` on failure.

    Subprocess rules per ADR-0013 D3: shell=False, argv list, no
    string concatenation. ``check=False`` so we can inspect stderr
    before raising.
    """
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(  # noqa: S603 — argv list, no shell
            [BINANCE_CLI_BIN, *argv, "--json"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            shell=False,  # explicit; default but defensive
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        raise BinanceCliError(
            f"binance-cli {argv[:2]} timed out after {timeout_s}s "
            f"(elapsed {elapsed_ms:.0f}ms)"
        ) from e
    except FileNotFoundError as e:
        raise BinanceCliError(
            f"binance-cli binary not found at {BINANCE_CLI_BIN!r}. "
            f"Install with `npm install -g @binance/binance-cli` or "
            f"set BINANCE_CLI_BIN to the correct path."
        ) from e

    elapsed_ms = (time.perf_counter() - t0) * 1000
    if proc.returncode != 0:
        # binance-cli emits a non-fatal EAGAIN warning to stderr when
        # stdin is not a TTY; ignore that one specifically. Anything
        # else is a real error.
        stderr = (proc.stderr or "").strip()
        if stderr and "EAGAIN" not in stderr:
            raise BinanceCliError(
                f"binance-cli {argv[:2]} exited {proc.returncode}: {stderr[:300]}"
            )
    return proc.stdout or ""


def _parse_json(stdout: str, argv_tail: list[str]) -> Any:
    """Parse JSON, tolerating the EAGAIN warning line that binance-cli
    emits on non-TTY stdin.

    The CLI prints its warning to stderr normally, but when called via
    subprocess it sometimes lands in stdout as a leading line that is
    NOT JSON. Strip any leading non-JSON lines.
    """
    if not stdout.strip():
        raise BinanceCliError(f"binance-cli {argv_tail} returned empty stdout")
    # Find the first JSON-looking line ("{" or "[") and start there.
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("{") or s.startswith("["):
            payload = "\n".join(lines[i:])
            break
    else:
        raise BinanceCliError(
            f"binance-cli {argv_tail} produced no JSON. First 200 chars: "
            f"{stdout[:200]!r}"
        )
    try:
        return json.loads(payload)
    except json.JSONDecodeError as e:
        raise BinanceCliError(
            f"binance-cli {argv_tail} JSON parse failed at col {e.colno}: "
            f"{payload[:200]!r}"
        ) from e


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_mark_price(
    symbol: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> MarkPrice:
    """Return the current mark price + funding snapshot for ``symbol``.

    Wraps ``binance-cli futures-usds mark-price --symbol <symbol>``.
    """
    argv = ["futures-usds", "mark-price", "--symbol", symbol]
    data = _parse_json(_run_cli(argv, timeout_s=timeout_s), argv)
    if not isinstance(data, dict):
        raise BinanceCliError(f"mark-price {symbol}: expected dict, got {type(data).__name__}")
    try:
        return MarkPrice(
            symbol=data["symbol"],
            mark_price=float(data["markPrice"]),
            index_price=float(data["indexPrice"]),
            estimated_settle_price=(
                float(data["estimatedSettlePrice"])
                if data.get("estimatedSettlePrice") not in (None, "")
                else None
            ),
            last_funding_rate=float(data["lastFundingRate"]),
            next_funding_time=int(data["nextFundingTime"]),
            time=int(data["time"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise BinanceCliError(
            f"mark-price {symbol}: missing or malformed field: {e}. "
            f"Payload keys: {list(data.keys())}"
        ) from e


def fetch_open_interest(
    symbol: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> OpenInterest:
    """Return the current open interest for ``symbol``.

    Wraps ``binance-cli futures-usds open-interest --symbol <symbol>``.
    """
    argv = ["futures-usds", "open-interest", "--symbol", symbol]
    data = _parse_json(_run_cli(argv, timeout_s=timeout_s), argv)
    if not isinstance(data, dict):
        raise BinanceCliError(
            f"open-interest {symbol}: expected dict, got {type(data).__name__}"
        )
    try:
        return OpenInterest(
            symbol=data["symbol"],
            open_interest=float(data["openInterest"]),
            time=int(data["time"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise BinanceCliError(
            f"open-interest {symbol}: missing or malformed field: {e}. "
            f"Payload keys: {list(data.keys())}"
        ) from e


def fetch_funding_history(
    symbol: str,
    *,
    limit: int = 10,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> list[FundingRate]:
    """Return the most recent ``limit`` funding rate entries for ``symbol``.

    Wraps ``binance-cli futures-usds get-funding-rate-history --symbol <symbol> --limit N``.
    """
    if not isinstance(limit, int) or limit <= 0:
        raise ValueError(f"limit must be a positive int, got {limit!r}")
    argv = [
        "futures-usds",
        "get-funding-rate-history",
        "--symbol", symbol,
        "--limit", str(limit),
    ]
    data = _parse_json(_run_cli(argv, timeout_s=timeout_s), argv)
    if not isinstance(data, list):
        raise BinanceCliError(
            f"funding history {symbol}: expected list, got {type(data).__name__}"
        )
    out: list[FundingRate] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(
                FundingRate(
                    symbol=entry["symbol"],
                    funding_time=int(entry["fundingTime"]),
                    funding_rate=float(entry["fundingRate"]),
                    mark_price=(
                        float(entry["markPrice"])
                        if entry.get("markPrice") not in (None, "")
                        else None
                    ),
                    rate_type=str(entry.get("rateType", "Regular")),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("funding history %s: skipping malformed entry %s", symbol, e)
            continue
    return out