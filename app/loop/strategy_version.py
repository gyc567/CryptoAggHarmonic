"""Strategy versioning — detect when repo strategy files change.

Renamed from ``skills_version`` to avoid collision with mattpocock/skills
agent skills in ``skills-lock.json``.

HISTORY.jsonl compatibility:
- Writes use ``strategy_version`` only.
- Reads accept either ``strategy_version`` or legacy ``skills_version``.
"""

from __future__ import annotations

import hashlib
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

    Supports both the new ``strategy_version`` field and the legacy
    ``skills_version`` field.
    """
    return record.get("strategy_version") or record.get("skills_version")


__all__ = [
    "DEFAULT_STRATEGY_FILES",
    "current_version",
    "save_version",
    "is_outdated",
    "read_recorded_version",
]
