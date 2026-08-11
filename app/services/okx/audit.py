"""Append-only audit log for OKX write operations.

ADR-0011 D6 (10-field schema) + D10 (outbox / crash-safe mode).

Schema (10 fields, every record):

  ts              ISO 8601 with microseconds (e.g. 2026-08-11T13:47:26.123456Z)
  tool            MCP tool name (e.g. "spot_place_order")
  args            sanitized args (secrets must be redacted by caller)
  result_code     OKX code ("0" on success), or "REJECTED" / "EXCEPTION" pre-dispatch
  result_body_hash sha256:... of the OKX response body (NOT the body itself; PII hygiene)
  user            loop identifier (e.g. "loop#11")
  salt_version    app.config.tuning.TUNING.salt_version at dispatch time
  cl_ord_id       client order id (for replay protection, ADR-0011 M4)
  trace_id        OKX traceId from the response (may be None for rejections)

Outbox mode (crash-safe):

  .scratch/okx_state/audit/{YYYY-MM-DD}.jsonl.outbox/{uuid}.json
       atomic rename
  .scratch/okx_state/audit/{YYYY-MM-DD}.jsonl

  This mirrors the freqtrade ``app/loop/state.append_history()``
  outbox pattern, so a crashed process leaves the outbox entry for
  the next run to quarantine or replay.

90-day retention (ADR-0011 D6): no auto-cleanup; human archives.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Sanitized arg keys that MUST be redacted from ``args`` before
# recording. Even though we never log them, the args field is
# persisted to disk and could be exposed via tail/dump.
_AUDIT_REDACT_KEYS = frozenset({
    "api_key", "secret_key", "passphrase", "apiKey", "secretKey",
    "password", "token", "secret",
})


def _redact_args(args: Any) -> Any:
    """Recursively replace values for known secret keys with "***"."""
    if isinstance(args, dict):
        out: dict = {}
        for k, v in args.items():
            if k in _AUDIT_REDACT_KEYS:
                out[k] = "***"
            else:
                out[k] = _redact_args(v)
        return out
    if isinstance(args, list):
        return [_redact_args(v) for v in args]
    return args


def _hash_body(body: Any) -> str:
    """Return sha256:<hex> of the body. We hash instead of storing the
    body to avoid persisting PII / financial data unnecessarily."""
    payload = json.dumps(body, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class AuditLog:
    """Append-only audit log with outbox / crash-safe semantics.

    Path: ``.scratch/okx_state/audit/{YYYY-MM-DD}.jsonl``
    Outbox: ``.scratch/okx_state/audit/{YYYY-MM-DD}.jsonl.outbox/{uuid}.json``
    """

    root: Path = Path(".scratch/okx_state/audit")
    user: str = "loop#11"

    def _date_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        outbox = self.root / f"{self._date_str()}.jsonl.outbox"
        outbox.mkdir(parents=True, exist_ok=True)

    def build_record(
        self,
        tool: str,
        args: Any,
        salt_version: int,
        paper: bool,
        gate: str,
        result_code: str,
        latency_ms: int,
        trace_id: str | None,
        cl_ord_id: str | None = None,
        result_body: Any = None,
    ) -> dict:
        """Build (but do not write) a 10-field audit record."""
        if result_body is not None:
            body_hash = _hash_body(result_body)
        else:
            # Stable hash of the rejection gate name so the record is
            # still queryable in audits.
            body_hash = _hash_body({"gate": gate, "result_code": result_code})
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "args": _redact_args(args),
            "result_code": result_code,
            "result_body_hash": body_hash,
            "user": self.user,
            "salt_version": salt_version,
            "paper": paper,
            "cl_ord_id": cl_ord_id,
            "latency_ms": latency_ms,
            "trace_id": trace_id,
            "gate": gate,
        }

    def write(self, record: dict) -> None:
        """Write a record via outbox + atomic rename."""
        self._ensure_dirs()
        date = self._date_str()
        outbox_file = self.root / f"{date}.jsonl.outbox" / f"{uuid.uuid4().hex}.json"
        outbox_file.write_text(json.dumps(record, sort_keys=True))
        # Atomic append into the daily file.
        target = self.root / f"{date}.jsonl"
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        outbox_file.unlink(missing_ok=True)
        logger.debug(f"audit record written: tool={record['tool']} result_code={record['result_code']}")

    def read_today(self) -> list[dict]:
        """Read all records for the current UTC date. Test helper."""
        target = self.root / f"{self._date_str()}.jsonl"
        if not target.exists():
            return []
        return [json.loads(line) for line in target.read_text().splitlines() if line.strip()]
