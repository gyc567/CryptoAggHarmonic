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


def promotion_checklist(
    max_drawdown: float | None = None,
    calmar_ratio: float | None = None,
    baseline_drawdown: float | None = None,
) -> list[str]:
    """Human-readable promotion steps (ADR-0010 D5: drawdown/Calmar/Shadow quant gates).

    Args:
        max_drawdown: Candidate max drawdown (fraction, e.g. 0.15 = 15%).
        calmar_ratio: Candidate Calmar ratio.
        baseline_drawdown: Baseline max drawdown for comparison.
    """
    checks = [
        "1. Accept candidate → write tuning_snapshots/pareto-{sha}.yaml",
        "2. Open PR editing app/config/tuning.py (never auto-merge)",
        "3. Review backtest metrics:",
        "   [ ] max_drawdown ≤ 2 × baseline_drawdown"
        + (f" (baseline={baseline_drawdown:.1%}, threshold={2*baseline_drawdown:.1%})"
           if baseline_drawdown else ""),
        "   [ ] Calmar ratio ≥ threshold"
        + (f" (candidate={calmar_ratio:.2f})" if calmar_ratio is not None else ""),
        "   [ ] Shadow mode running ≥ 7 days without drawdown anomaly",
        "   [ ] source=freqtrade_hyperopt salt_version traceable in HISTORY.jsonl",
        "4. Merge + SIGHUP/restart gunicorn workers",
    ]
    return checks
