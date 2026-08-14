"""FT Strategy audit log — D-FT-12.

Append-only JSONL log of FT Strategy UI operations. Lives at
``$LOOP_STATE_ROOT/ft_strategy/audit.jsonl`` and is intentionally
separate from ``HISTORY.jsonl`` so UI actions do not enter the
``okx_*`` / ``freqtrade_hyperopt`` source mutex matrix.

Per ADR-0012 D12 + ``docs/plans/ft-strategy-ui-integration.md`` §3.3:
  * every record's ``source`` is hard-coded to ``ft_strategy_ui``
  * the file is append-only; there is no UPDATE / DELETE API
  * atomic ``open(..., "a") + write + close`` is fine because each
    record is a single JSON line shorter than PIPE_BUF (4096 B)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

#: Fixed source value. D-FT-12 invariant — callers cannot override it.
SOURCE_FT_STRATEGY_UI = "ft_strategy_ui"

#: Resolved audit log path. Re-read at every call so test fixtures that
#: mutate ``LOOP_STATE_ROOT`` are honored without re-importing this module.
def _audit_path() -> Path:
    return Path(os.environ.get("LOOP_STATE_ROOT", ".scratch/loop_state")) / "ft_strategy" / "audit.jsonl"


def _now_iso_utc() -> str:
    """Return current UTC time as ISO-8601 with ``Z`` suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_audit(
    event_type: str,
    strategy_id: str,
    *,
    version: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Append one record to the audit log and return the written record.

    ``source`` is always ``ft_strategy_ui``; attempts to pass a
    conflicting ``source`` kwarg are ignored.
    """
    record: dict[str, Any] = {
        "timestamp": _now_iso_utc(),
        "event_type": event_type,
        "strategy_id": strategy_id,
        "source": SOURCE_FT_STRATEGY_UI,
    }
    if version is not None:
        record["version"] = version
    # Caller-supplied extras flow in, but ``source`` / ``timestamp`` are
    # owned by this module.
    for key, value in extra.items():
        if key in {"source", "timestamp"}:
            continue
        record[key] = value

    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    # Single open+write+close keeps each append atomic on POSIX when the
    # line is shorter than PIPE_BUF (4096 B on Linux/macOS).
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")

    return record


def read_audit() -> Iterator[dict[str, Any]]:
    """Yield audit records in append order. Missing file yields nothing."""
    path = _audit_path()
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


#: Re-resolved on every access so test fixtures that mutate
#: ``LOOP_STATE_ROOT`` are honored without re-importing this module.


def __getattr__(name: str) -> Any:
    if name == "AUDIT_PATH":
        return _audit_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
