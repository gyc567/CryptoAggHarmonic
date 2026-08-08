"""TUNING live-promotion gate.

Live gunicorn workers each hold their own ``TUNING`` copy. Search-loop
``apply_tuning()`` must never be treated as a production promotion.

Promotion path (ADR-0003 D9):

1. accepted candidate → ``tuning_snapshots/pareto-{sha}.yaml``
2. human PR that edits ``app/config/tuning.py``
3. deploy / SIGHUP so workers reload

This module is the code-side checklist helpers; ``docs/loop-state/gate.yaml``
denylists ``app/config/tuning.py`` so loops cannot auto-merge that path.
"""

from __future__ import annotations

from pathlib import Path

LIVE_TUNING_PATH = "app/config/tuning.py"


def is_live_tuning_path(path: str | Path) -> bool:
    """True if ``path`` is the live TUNING constants module."""
    p = Path(path).as_posix()
    return p == LIVE_TUNING_PATH or p.endswith("/" + LIVE_TUNING_PATH)


def promotion_allowed_for_files(paths: list[str]) -> tuple[bool, str]:
    """Return (ok, reason). Fail if any path is live TUNING (must be human PR)."""
    for path in paths:
        if is_live_tuning_path(path):
            return (
                False,
                f"live TUNING promotion blocked: {path} "
                f"(edit only via human PR + SIGHUP; see ADR-0003 D9)",
            )
    return True, "ok"


def promotion_checklist() -> list[str]:
    """Human-readable promotion steps."""
    return [
        "1. Accept candidate → write tuning_snapshots/pareto-{sha}.yaml",
        "2. Open PR editing app/config/tuning.py (never auto-merge)",
        "3. Review backtest metrics (drawdown / Calmar gates)",
        "4. Merge + SIGHUP/restart gunicorn workers",
    ]
