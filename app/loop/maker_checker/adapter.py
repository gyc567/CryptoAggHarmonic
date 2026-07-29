"""Adapter that fuses :class:`app.loop.checker.check_candidate` (M4)
with the optional Maker-Checker :class:`MakerCheckerRunner`.

Why a separate module? Two reasons:

1. ``app.loop.driver`` imports this module lazily, so the heavy
   Maker-Checker chain (LLM backend, calibration) is **not** loaded in
   the existing single-generation CLI flow unless it is requested.
2. The audit §2.9 rollback lever (``MAKER_CHECKER_ENABLED=false``)
   short-circuits to the M4-only path without touching any other file.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.loop.checker import CheckerVerdict, check_candidate
from app.loop.maker_checker.runner import (
    MakerCheckerRunner,
    feature_enabled,
)
from app.loop.maker_checker.schemas import MergeResult
from app.loop.worker import CandidateResult


logger = logging.getLogger("app.loop.maker_checker.adapter")


def evaluate_candidate(
    candidate: CandidateResult,
    *,
    runner: Optional[MakerCheckerRunner] = None,
    parent_metrics: dict | None = None,
) -> MergeResult | CheckerVerdict:
    """Return the merged M4+LLM result, or M4-only when disabled.

    The return type is a union for backwards compatibility: when the
    feature flag is off we return the same :class:`CheckerVerdict` the
    driver has always used. Callers that opt in to the new behaviour
    can narrow on :class:`MergeResult`.
    """
    m4 = check_candidate(candidate, parent_metrics=parent_metrics)
    if runner is None or not feature_enabled():
        return m4

    merged = runner.evaluate(candidate, parent_metrics=parent_metrics)

    # Re-derive a CheckerVerdict whose decision is the merge result.
    # Existing drivers only look at ``decision`` + ``confidence`` so
    # preserving that shape avoids touching their code.
    from app.loop.checker import CheckerVerdict

    return CheckerVerdict(
        candidate_id=candidate.candidate_id,
        decision=merged.final_decision,
        confidence=merged.final_score,
        reasons=list(merged.trigger_reasons),
        flags=[],
    )


__all__ = ["evaluate_candidate"]