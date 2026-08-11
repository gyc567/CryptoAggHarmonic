"""OKX fill → HISTORY.jsonl round-trip.

Mirrors ``app/services/freqtrade/handshake.py`` but for OKX. The
output record shape is the same as freqtrade's so the existing
Pareto / Maker-Checker consumers can handle both sources.

The OKX loop's source values are ``okx_paper`` (paper/demo mode,
default) and ``okx_live`` (real OKX, requires ``OKX_ALLOW_LIVE=1``
+ ``promotion_checklist()``). Source mutex enforcement happens in
``app.loop.state.append_history()`` (ADR-0011 D11).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from app.loop.state import append_history, SourceMutexError

logger = logging.getLogger(__name__)

# Path resolution honors LOOP_STATE_ROOT (same env var as freqtrade
# handshake) so tests can redirect to a tmp dir. The freqtrade
# handshake hard-codes ".scratch/loop_state" — we read env here so
# OKX-fill tests can isolate without touching the repo's .scratch.
_LOOP_STATE_ROOT = Path(os.environ.get("LOOP_STATE_ROOT", ".scratch/loop_state"))
HISTORY_PATH = _LOOP_STATE_ROOT / "HISTORY.jsonl"
OUTBOX_DIR = _LOOP_STATE_ROOT / "HISTORY.jsonl.outbox"
OUTBOX_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class OKXFill:
    """An OKX spot fill, mapped into loop domain format."""

    uuid: str
    instId: str
    side: str
    fillPx: float
    fillSz: float
    fee: float
    ts: str
    ordId: str
    clOrdId: str
    paper: bool
    salt_version: int = 1
    source: str = ""  # "okx_paper" or "okx_live"; set in __post_init__

    def __post_init__(self) -> None:
        if not self.source:
            self.source = "okx_paper" if self.paper else "okx_live"


def write_fill_to_history(fill: OKXFill, params: dict | None = None) -> None:
    """Write an OKX fill to HISTORY.jsonl via outbox.

    Args:
        fill: The OKX fill to record.
        params: Optional params snapshot (e.g. salt-version-tagged TUNING
            fields that produced the order). Used by the Pareto / maker-
            checker consumers.

    Raises:
        SourceMutexError: when a conflicting source already exists for
            the same candidate_id (ADR-0011 D11). Caller should NOT
            retry — the conflict is deliberate.
    """
    record = {
        "candidate_id": f"okx-{fill.uuid[:12]}",
        "gen": -1,  # OKX is not a CMA-ES generation
        "cluster": "okx_execution",
        "decision": "okx_fill_recorded",
        "instrument": fill.instId,
        "side": fill.side,
        "fill_px": fill.fillPx,
        "fill_sz": fill.fillSz,
        "fee": fill.fee,
        "ordId": fill.ordId,
        "clOrdId": fill.clOrdId,
        "params": params or {},
        "timestamp": fill.ts,
        "source": fill.source,
        "salt_version": fill.salt_version,
        "paper": fill.paper,
    }
    # Outbox + atomic append. SourceMutexError propagates so callers
    # can distinguish deliberate conflicts from transient I/O errors.
    outbox_file = OUTBOX_DIR / f"{fill.uuid}.json"
    outbox_file.write_text(json.dumps(record))
    try:
        append_history(record, root=_LOOP_STATE_ROOT)
        outbox_file.unlink(missing_ok=True)
        logger.info(f"okx fill {fill.uuid} written to HISTORY.jsonl (source={fill.source})")
    except SourceMutexError:
        # Caller wants to know about mutex conflicts; clean outbox
        # so we don't leak on retry-from-outbox.
        outbox_file.unlink(missing_ok=True)
        raise
    except Exception as e:
        logger.warning(f"append_history failed for {fill.uuid}, leaving in outbox: {e}")
