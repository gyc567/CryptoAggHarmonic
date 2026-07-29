"""Skills versioning — detect when repo skills / heuristics change so the
loop can mark stale Pareto points.

The loop emits tuning snapshots + decisions into ``loop_state/``. If the
code that produced those decisions (the strategies, validators, signal
engine) has changed since, the historical decisions are no longer
comparable to the new ones. We hash the *strategic* Python files (not
data, not logs) and store the hash alongside each generation's
HISTORY.jsonl record.

Operators can then inspect STATE.md and see e.g.:

    skills_version: abc123 (3 days ago)
    latest_run_decision: accepted (skills_version matches)
    decision 4 days ago: accepted (skills_version DIFFERENT — review!)

This module is intentionally trivial — it's a file hash + a compare.
The interesting part is the policy in the driver (plan §6): tag every
HISTORY line with the skills_version at run time.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable

from app.loop.state import DEFAULT_ROOT, atomic_write_json


# Default set of files that affect strategy decisions. Keep this small —
# these are the files the operator would expect a Pareto change to track.
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
    repo_root: Path | None = None,
    extra_files: Iterable[str] = (),
) -> str:
    """Compute a short hash covering all strategic files.

    ``extra_files`` can be added by the operator (e.g. a custom
    extension) without touching :data:`DEFAULT_STRATEGY_FILES`.
    """
    repo_root = repo_root or Path(os.getcwd())
    files = list(DEFAULT_STRATEGY_FILES) + list(extra_files)
    h = hashlib.sha256()
    for relpath in sorted(files):
        path = repo_root / relpath
        # Include path so swapping file names still changes the hash.
        h.update(relpath.encode())
        h.update(_hash_file(path).encode())
    return h.hexdigest()[:12]


def save_version(repo_root: Path | None = None) -> str:
    """Compute + persist the current skills version. Returns the hash."""
    from app.loop.state import ensure_root  # late import to avoid cycle
    root = (repo_root or Path(os.getcwd())) / DEFAULT_ROOT
    ensure_root(root)
    version = current_version(repo_root)
    atomic_write_json(
        root / "skills_version.json",
        {"version": version, "ts": __import__("time").time()},
    )
    return version


def is_outdated(current: str, recorded: str) -> bool:
    """True if the two versions don't match.

    Used by STATE.md renderers to flag historical decisions that were
    made under an old skill set.
    """
    return current != recorded