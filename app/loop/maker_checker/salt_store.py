"""Salt persistence for Maker-Checker isolation.

Salts are stored in .scratch/loop_state/salt.json (gitignored).
Salt is created once per session and reused for all Maker→Checker calls
within that session to maintain isolation.

For reproducibility, the salt + salt_version are recorded in HISTORY.jsonl
so a given run can be reconstructed from its records.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

# Late import to avoid circular dependency at module level
def _get_salt_path() -> Path:
    from app.loop.state import DEFAULT_ROOT
    import os
    root = Path(os.environ.get("LOOP_STATE_ROOT", str(DEFAULT_ROOT)))
    return root / "salt.json"


def make_salt(length: int = 32) -> str:
    """Generate a random salt string."""
    import secrets
    return secrets.token_hex(length)


def get_or_create_salt() -> str:
    """Get the current salt (from file) or create a new one.

    The salt persists across loop runs on the same machine, enabling
    reproducibility audits. It is NOT meant for cross-machine sharing.
    """
    salt_file = _get_salt_path()
    salt_file.parent.mkdir(parents=True, exist_ok=True)

    if salt_file.exists():
        try:
            data = json.loads(salt_file.read_text())
            return data["salt"]
        except (json.JSONDecodeError, KeyError):
            pass  # corrupted, regenerate

    return _write_salt(make_salt())


def _write_salt(salt: str) -> str:
    """Write salt to disk and return it."""
    salt_file = _get_salt_path()
    salt_file.parent.mkdir(parents=True, exist_ok=True)
    salt_file.write_text(json.dumps({
        "salt": salt,
        "created_at": time.time(),
    }))
    return salt


def rotate_salt() -> str:
    """Manually rotate the salt (for security incident response).

    Generates a NEW salt and overwrites the file.
    Call this when a potential salt compromise is suspected.
    """
    return _write_salt(make_salt())


def get_salt_version() -> int:
    """Get the current salt version number (increments on each rotation)."""
    salt_file = _get_salt_path()
    if not salt_file.exists():
        return 0
    try:
        data = json.loads(salt_file.read_text())
        return int(data.get("version", 1))
    except (json.JSONDecodeError, KeyError):
        return 0


def get_salt_info() -> dict:
    """Return salt metadata for audit logging."""
    salt_file = _get_salt_path()
    if not salt_file.exists():
        return {"salt": None, "created_at": None, "version": 0}
    try:
        data = json.loads(salt_file.read_text())
        return {
            "salt": data.get("salt"),
            "created_at": data.get("created_at"),
            "version": data.get("version", 1),
        }
    except (json.JSONDecodeError, KeyError):
        return {"salt": None, "created_at": None, "version": 0}
