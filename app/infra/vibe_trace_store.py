"""Trace storage for vibe runs.

A trace captures the full agent execution: messages, LLM requests/responses,
tool calls, and timing. Phase 1 stores traces on the local filesystem.
Production can override the directory to a mounted volume or object storage
via ``VIBE_TRACE_DIR``.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class VibeTraceStore:
    """Store and retrieve run traces."""

    def __init__(self, base_dir: Optional[str] = None):
        default_dir = os.path.join(os.getcwd(), "vibe_traces")
        self.base_dir = Path(base_dir or os.getenv("VIBE_TRACE_DIR", default_dir))
        self.base_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.enabled = os.getenv("VIBE_ENABLE_TRACE", "1") == "1"
        self.retention_days = int(os.getenv("VIBE_TRACE_RETENTION_DAYS", "30"))
        if self.enabled and self.retention_days > 0:
            self._cleanup_old_traces()

    def _cleanup_old_traces(self) -> None:
        """Remove trace files older than ``retention_days`` to control disk usage."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        removed = 0
        for user_dir in self.base_dir.iterdir():
            if not user_dir.is_dir():
                continue
            for path in user_dir.glob("*.json"):
                try:
                    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                    if mtime < cutoff:
                        path.unlink()
                        removed += 1
                except Exception as e:
                    logger.warning("Failed to cleanup trace %s: %s", path, e)
            # Remove empty user directories.
            try:
                if not any(user_dir.iterdir()):
                    user_dir.rmdir()
            except Exception as e:
                logger.debug("rmdir cleanup failed (perm/race): %s", e)
        if removed:
            logger.info(
                "Cleaned up %d trace files older than %d days",
                removed,
                self.retention_days,
            )

    def save_trace(
        self,
        run_id: str,
        user_id: str,
        trace: dict,
    ) -> str | None:
        """Save a trace file. Returns the file path or None if disabled."""
        if not self.enabled:
            return None

        # Store under user-scoped directory for isolation.
        user_dir = self.base_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        path = user_dir / f"{run_id}.json"
        trace["meta"] = {
            "run_id": run_id,
            "user_id": user_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            path.write_text(
                json.dumps(trace, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            return str(path)
        except Exception as e:
            logger.warning("Failed to save trace for run %s: %s", run_id, e)
            return None

    def get_trace(self, run_id: str, user_id: str) -> dict | None:
        """Retrieve a trace file if it exists and belongs to the user."""
        path = self.base_dir / user_id / f"{run_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to read trace %s: %s", run_id, e)
            return None

    def delete_trace(self, run_id: str, user_id: str) -> bool:
        """Delete a trace file."""
        path = self.base_dir / user_id / f"{run_id}.json"
        try:
            if path.exists():
                path.unlink()
            return True
        except Exception as e:
            logger.warning("Failed to delete trace %s: %s", run_id, e)
            return False
