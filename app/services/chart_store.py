"""Local chart persistence: save, serve-path validation, and TTL cleanup.

Charts are stored under ``instance/charts/`` (already gitignored) so the
dashboard can render them without Supabase Storage. The module is deliberately
tiny: one directory, three functions, no state.
"""

import logging
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CHART_DIR = Path("instance/charts")
CHART_TTL_SECONDS = 24 * 3600

# analysis_id is a uuid hex fragment; refuse anything else outright.
_NAME_RE = re.compile(r"^[a-f0-9-]{8,64}$")


def is_valid_chart_name(name: str) -> bool:
    """Whitelist check against path traversal / unexpected names."""
    return bool(_NAME_RE.match(name))


def save_chart_locally(
    analysis_id: str,
    image_bytes: bytes,
    chart_dir: Optional[Path] = None,
    ttl_seconds: int = CHART_TTL_SECONDS,
) -> str | None:
    """Persist PNG bytes and return the relative serving path.

    Also garbage-collects files older than ``ttl_seconds`` so the directory
    cannot grow unbounded. Returns None when the id is invalid or the write
    fails (chart distribution is best-effort and never blocks analysis).
    """
    if not is_valid_chart_name(analysis_id):
        logger.warning("Refusing to save chart with invalid name: %r", analysis_id)
        return None
    if chart_dir is None:
        chart_dir = CHART_DIR
    try:
        chart_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_old_charts(chart_dir, ttl_seconds)
        path = chart_dir / f"{analysis_id}.png"
        path.write_bytes(image_bytes)
        return str(path)
    except OSError:
        logger.exception("Failed to save chart locally for %s", analysis_id)
        return None


def chart_file_path(name: str, chart_dir: Optional[Path] = None) -> Path | None:
    """Resolve a chart name to an existing file path, or None."""
    if not is_valid_chart_name(name):
        return None
    if chart_dir is None:
        chart_dir = CHART_DIR
    path = chart_dir / f"{name}.png"
    # Resolve to an absolute path: flask.send_file interprets relative paths
    # against the app root package, not the process CWD.
    return path.resolve() if path.is_file() else None


def _cleanup_old_charts(chart_dir: Path, ttl_seconds: int) -> None:
    cutoff = time.time() - ttl_seconds
    for old in chart_dir.glob("*.png"):
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            logger.warning("Failed to remove old chart %s", old)
