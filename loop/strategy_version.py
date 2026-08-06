"""Strategy versioning — detect when repo strategy files change.

Renamed from skills_version.py to avoid collision with
mattpocock/skills agent skills in skills-lock.json.

The loop emits tuning snapshots + decisions into ``loop_state/``. If the
code that produced those decisions (the strategies, validators, signal
engine) has changed since, the historical decisions are no longer
comparable to the new ones. We hash the *strategic* Python files (not
data, not logs) and store the hash alongside each generation's
HISTORY.jsonl record.

Operators can then inspect STATE.md and see e.g.::

    strategy_version: abc123 (3 days ago)
    latest_run_decision: accepted (strategy_version matches)
    decision 4 days ago: accepted (strategy_version DIFFERENT — review!)

HISTORY.jsonl backward compatibility:
- Reads both ``skills_version`` and ``strategy_version`` fields
- Writes use ``strategy_version`` only
- A backfill script (not part of this module) migrates old records
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional

from app.loop.state import DEFAULT_ROOT, atomic_write_json

DEFAULT_STRATEGY_FILES = (
    "app/config/tuning.py",
    "app/domain/signals.py",
    "app/domain/validation.py",
    "app/services/signal_engine.py",
    "app/services/discipline_filters.py",
    "app/services/macro_bias.py",
    ".scratch/backtest/run_backtest_v3.py",
)


def _hash_file(path: Path) -> str:
    if not path.exists():
        return "missing"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def current_version(
    repo_root: Optional[Path] = None,
    extra_files: Iterable[str] = (),
) -> str:
    """Compute a short hash covering all strategic files."""
    repo_root = repo_root or Path(os.getcwd())
    files = list(DEFAULT_STRATEGY_FILES) + list(extra_files)
    h = hashlib.sha256()
    for relpath in sorted(files):
        path = repo_root / relpath
        h.update(relpath.encode())
        h.update(_hash_file(path).encode())
    return h.hexdigest()[:12]


def save_version(repo_root: Optional[Path] = None) -> str:
    """Compute + persist the current strategy version. Returns the hash."""
    from app.loop.state import ensure_root  # late import to avoid cycle

    root = (repo_root or Path(os.getcwd())) / DEFAULT_ROOT
    ensure_root(root)
    version = current_version(repo_root)
    atomic_write_json(
        root / "strategy_version.json",
        {"version": version, "ts": time.time()},
    )
    return version


def is_outdated(current: str, recorded: str) -> bool:
    """True if the two versions don't match."""
    return current != recorded


def read_recorded_version(record: dict[str, Any]) -> Optional[str]:
    """Read strategy version from a HISTORY.jsonl record.

    Supports both the old ``skills_version`` field and the new
    ``strategy_version`` field for backward compatibility.
    """
    return record.get("strategy_version") or record.get("skills_version")


__all__ = [
    "current_version",
    "save_version",
    "is_outdated",
    "read_recorded_version",
    "DEFAULT_STRATEGY_FILES",
]
