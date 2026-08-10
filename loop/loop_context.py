"""
Scratch → Episodic promotion engine.

Scratch:  per-inference session memory (in-memory dict, lost on exit).
Episodic: day–week retention promoted to docs/loop-state/ by this module.

Policy
------
A scratch entry is promoted when BOTH:

1. ``len(value) >= 256``  —  enough signal to be useful later.
2. The entry has survived >= 24 h  —  not just a throwaway intermediate.

Promotion writes JSONL to ``docs/loop-state/episodic-memory.jsonl``, one
record per line::

    {"ts": "2026-08-06T10:00:00Z", "key": "...", "value": "..."}

The file is append-only; we never mutate old lines.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from loop.loop_gate import load_gate_config

# ── config ────────────────────────────────────────────────────────────────────

STATE_DIR = Path("docs/loop-state")
EPISODIC_FILE = STATE_DIR / "episodic-memory.jsonl"
DURABLE_FILE = STATE_DIR / "durable-facts.md"
METADATA_FILE = STATE_DIR / "memory-constraints.md"
BUDGET_FILE = STATE_DIR / "memory-budget.md"

MIN_VALUE_LEN = 256      # chars
MIN_AGE_HOURS = 24       # hours before promotion is considered

# ── scratch store ─────────────────────────────────────────────────────────────

_scratch: dict[str, tuple[str, float]] = {}   # key → (value, first_seen_ts)
_scratch_lock = threading.Lock()


def scratch_put(key: str, value: str) -> None:
    """Store or update a scratch entry with current timestamp."""
    with _scratch_lock:
        _scratch[key] = (value, time.time())


def scratch_get(key: str) -> str | None:
    """Retrieve a scratch value, or None if not found."""
    with _scratch_lock:
        val = _scratch.get(key)
        return val[0] if val else None
# ── promotion logic ───────────────────────────────────────────────────────────

def should_promote(key: str, value: str, first_seen: float) -> bool:
    """Return True when a scratch entry meets both policy criteria."""
    if len(value) < MIN_VALUE_LEN:
        return False
    age_hours = (time.time() - first_seen) / 3600
    if age_hours < MIN_AGE_HOURS:
        return False
    # gate check: verify memory constraints allow promotion of this key
    try:
        gate = load_gate_config()
    except Exception:
        return False  # fail open; don't block on gate errors
    denylist = gate.get("denylist", [])
    for pattern in denylist:
        if pattern.lower() in key.lower() or pattern.lower() in value.lower():
            return False
    return True


def promote_all() -> int:
    """
    Scan scratch, promote eligible entries to episodic-memory.jsonl.

    Returns the number of entries promoted.
    """
    if not EPISODIC_FILE.exists():
        EPISODIC_FILE.parent.mkdir(parents=True, exist_ok=True)
        EPISODIC_FILE.write_text("")

    # Collect eligible keys under lock, then promote outside the lock.
    to_delete: list[str] = []
    with _scratch_lock:
        for key, (value, first_seen) in list(_scratch.items()):
            if should_promote(key, value, first_seen):
                to_delete.append(key)

    promoted = 0
    for key in to_delete:
        with _scratch_lock:
            _, first_seen = _scratch.get(key, (None, None))
            if first_seen is None:
                continue
            value, _ = _scratch[key]
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "key": key,
            "value": value,
        }
        with EPISODIC_FILE.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        with _scratch_lock:
            del _scratch[key]
        promoted += 1

    return promoted


def load_episodic(limit: int = 100) -> list[dict[str, Any]]:
    """Load the most recent ``limit`` episodic records, newest last."""
    if not EPISODIC_FILE.exists():
        return []
    lines = EPISODIC_FILE.read_text().strip().splitlines()
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records[-limit:]


def scratch_size() -> int:
    """Return current scratch entry count."""
    with _scratch_lock:
        return len(_scratch)


def clear_scratch() -> None:
    """Clear all scratch entries. Used by memory-budget enforcement."""
    with _scratch_lock:
        _scratch.clear()


# ── Durable Facts promotion ──────────────────────────────────────────────────

def promote_episodic_to_durable(
    episodic_key: str,
    durable_summary: str,
    source: str,
    content: str,
) -> str:
    """
    Promote an episodic memory entry to Durable Facts.

    Promotion writes a new entry to durable-facts.md. Old entries are NEVER
    deleted; they receive a ``superseded_by`` field pointing to the new uuid.

    Args:
        episodic_key: The key in episodic-memory.jsonl being promoted
        durable_summary: Short human-readable summary (used as heading)
        source: Git commit hash or decision reference
        content: Full fact content

    Returns:
        The new durable fact uuid
    """
    import uuid as uuid_lib

    durable_uuid = uuid_lib.uuid4().hex[:8]
    now = datetime.now(timezone.utc).isoformat()

    # Mark existing entries with same episodic_key as superseded
    _mark_superseded(episodic_key, durable_uuid)

    # Build new entry in Markdown format matching durable-facts.md spec
    new_entry = (
        f"### [{durable_uuid}] — {durable_summary}\n"
        f"- **Created**: {now}\n"
        f"- **Source**: {source}\n"
        f"- **Content**: {content}\n"
        f"- **superseded_by**: _none_\n"
    )

    # Read existing content, replace the "<!-- Entries are append-only -->" marker
    durable_md = DURABLE_FILE
    if durable_md.exists():
        content_text = durable_md.read_text()
    else:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        content_text = "# Durable Facts — cryptoagg\n\n> Append-only log of durable project facts.\n> NEVER delete entries — mark superseded with `superseded_by`.\n\n## Entries\n\n<!-- Entries are append-only. Format:\n\n### [uuid] — {fact summary}\n- **Created**: {date}\n- **Content**: {description}\n- **Source**: {git commit or decision reference}\n- **superseded_by**: {uuid if applicable}\n\n-->\n"

    # Replace the "## Entries" section's end marker with the new entry
    marker = "<!-- Entries are append-only. Format:"
    if marker in content_text:
        # Insert before the format comment block
        idx = content_text.find(marker)
        header = content_text[:idx].rstrip() + "\n\n"
        tail = content_text[idx:]
        new_content = header + new_entry + "\n" + tail
    else:
        new_content = content_text + "\n" + new_entry

    durable_md.write_text(new_content)
    return durable_uuid


def _mark_superseded(episodic_key: str, new_uuid: str) -> None:
    """
    Find all Durable Facts entries for the same episodic_key and mark them superseded.

    The ``superseded_by`` field in the Markdown is updated to point to new_uuid.
    This is a line-level edit to avoid rewriting the whole file.
    """
    if not DURABLE_FILE.exists():
        return

    lines = DURABLE_FILE.read_text().splitlines()
    in_section = False
    updated_lines: list[str] = []

    for line in lines:
        if f"**Content**: {episodic_key}" in line or episodic_key in line:
            in_section = True
        if in_section and line.strip().startswith("- **superseded_by**: _none_"):
            updated_lines.append(f"- **superseded_by**: {new_uuid}")
            in_section = False
            continue
        updated_lines.append(line)

    DURABLE_FILE.write_text("\n".join(updated_lines) + "\n")


def hygiene() -> dict[str, int]:
    """
    Run memory hygiene: promote eligible scratch entries and clean old episodics.

    Returns a summary dict with counts of promoted, cleaned, and remaining entries.
    """
    promoted = promote_all()

    # Clean episodic entries older than 14 days
    cleaned = 0
    if EPISODIC_FILE.exists():
        cutoff = time.time() - 14 * 24 * 3600
        remaining: list[str] = []
        for line in EPISODIC_FILE.read_text().splitlines():
            if not line:
                continue
            try:
                rec = json.loads(line)
                rec_time = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
                if rec_time.timestamp() >= cutoff:
                    remaining.append(line)
                else:
                    cleaned += 1
            except Exception:
                remaining.append(line)
        EPISODIC_FILE.write_text("\n".join(remaining) + "\n")

    return {
        "promoted": promoted,
        "cleaned": cleaned,
        "episodic_remaining": len(remaining) if EPISODIC_FILE.exists() else 0,
        "scratch_remaining": scratch_size(),
    }
