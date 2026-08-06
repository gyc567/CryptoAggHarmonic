"""Gate checker — mechanical enforcement of gate.yaml rules.

Validates that proposed changes don't touch denylisted paths
and that auto-merge conditions are satisfied.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path
from typing import Any

LOOP_STATE_ROOT = Path(os.environ.get("LOOP_STATE_ROOT", ".scratch/loop_state"))
GATE_FILE = Path("docs/loop-state/gate.yaml")


def load_gate_config() -> dict[str, Any]:
    """Load gate.yaml, returning a dict with defaults for missing keys."""
    import yaml  # lazy import to avoid hard dep

    defaults: dict[str, Any] = {
        "denylist": [],
        "always_exclude": [],
        "auto_merge_allowlist": [],
        "rate_limits": {},
        "loop_paused": False,
        "min_readiness_score": 58,
    }
    if not GATE_FILE.exists():
        return defaults
    with open(GATE_FILE) as f:
        cfg = yaml.safe_load(f) or {}
    return {**defaults, **cfg}


def check_path(path: str) -> tuple[bool, str]:
    """Check if a path is denylisted.

    Returns (allowed, reason).
    """
    cfg = load_gate_config()
    if cfg.get("loop_paused"):
        return False, "loop_paused=true in gate.yaml"

    path_str = str(path)
    for pattern in cfg.get("always_exclude", []):
        if fnmatch.fnmatch(path_str, pattern):
            return False, f"always_exclude: {pattern}"
    for pattern in cfg.get("denylist", []):
        if fnmatch.fnmatch(path_str, pattern):
            return False, f"denylist: {pattern}"
    return True, "ok"


def check_files(paths: list[str]) -> dict[str, Any]:
    """Check a list of file paths against gate rules.

    Returns a dict with 'passed', 'violations', and 'summary'.
    """
    violations: list[dict[str, str]] = []
    for p in paths:
        allowed, reason = check_path(p)
        if not allowed:
            violations.append({"path": p, "reason": reason})

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "summary": f"{len(violations)} violation(s)" if violations else "all clear",
    }


def check_kill_switch() -> tuple[bool, str]:
    """Check if the kill switch is active."""
    cfg = load_gate_config()
    paused = cfg.get("loop_paused", False)
    reason = cfg.get("pause_reason", "")
    return not paused, reason if paused else "ok"


def main() -> int:
    """CLI entry point: check gate.yaml for current state."""
    import yaml

    if not GATE_FILE.exists():
        print("NO_GATE_FILE")
        return 1

    cfg = load_gate_config()
    paused = cfg.get("loop_paused", False)
    min_score = cfg.get("min_readiness_score", 58)

    print(f"loop_paused: {paused}")
    print(f"min_readiness_score: {min_score}")
    print(f"denylist_entries: {len(cfg.get('denylist', []))}")
    print(f"auto_merge_sources: {[s.get('source') for s in cfg.get('auto_merge_allowlist', [])]}")

    if paused:
        print(f"PAUSED: {cfg.get('pause_reason', 'no reason')}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
