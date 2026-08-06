"""Arbiter — decision tree that fuses M4 heuristics + LLM Checker + Maker.

The Arbiter is the single point that decides whether a candidate is
accepted, rejected, or sent to human review. It does **not** run any
LLM call itself — both inputs are produced upstream by
:mod:`app.loop.checker` (M4 heuristics) and
:mod:`app.loop.maker_checker.checker_agent` (LLM).

Decision tree (audit §2.6, v1.1):

    1. ``m4 == rejected``                     → rejected (hard constraint)
    2. ``m4 == promising`` AND ``llm == accept``  → accepted (weighted merge)
    3. ``m4 == promising`` AND ``llm == reject`` → rejected (LLM sees more)
    4. ``m4 == suspicious`` AND ``llm == accept`` → suspicious_to_human
    5. ``m4 == suspicious`` AND ``llm == reject`` → rejected
    6. ``gap > maker_checker_gap_threshold`` AND ``llm == accept``
                                                  → suspicious_to_human

The final score is the weighted merge::

    final = maker_weight * maker_self_score + checker_weight * checker_score

with ``maker_weight + checker_weight = 1.0``. The 5-D Pareto extension
adds ``checker_confidence`` as the new dimension; the legacy 4-D points
carry ``checker_confidence = None`` and are treated as ``-inf`` in
``dominates()`` so they never dominate a new point but can be dominated
(back-compat audit §2.6).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.loop.checker import CheckerVerdict
from app.loop.maker_checker.schemas import (
    MergeResult,
    Proposal,
    Verdict,
    make_merge_result,
)

logger = logging.getLogger("app.loop.maker_checker.arbiter")


VALID_M4 = ("promising", "suspicious", "rejected")


# ---- Configuration --------------------------------------------------------


@dataclass(frozen=True)
class ArbiterConfig:
    """Static configuration for an :class:`Arbiter`.

    Fields:

    * ``maker_weight`` / ``checker_weight`` — weights for the weighted
      merge. Must satisfy ``maker_weight + checker_weight ≈ 1.0``.
    * ``maker_checker_gap_threshold`` — if ``abs(maker_score -
      checker_score) > threshold`` AND the candidate would otherwise be
      accepted, divert to human review.
    """

    maker_weight: float = 0.4
    checker_weight: float = 0.6
    maker_checker_gap_threshold: float = 0.4

    def __post_init__(self) -> None:
        if not 0.0 <= self.maker_weight <= 1.0:
            raise ValueError(f"maker_weight must be in [0, 1]; got {self.maker_weight}")
        if not 0.0 <= self.checker_weight <= 1.0:
            raise ValueError(f"checker_weight must be in [0, 1]; got " f"{self.checker_weight}")
        if abs(self.maker_weight + self.checker_weight - 1.0) > 0.01:
            raise ValueError(f"maker_weight + checker_weight must equal 1.0; got " f"{self.maker_weight + self.checker_weight}")
        if not 0.0 <= self.maker_checker_gap_threshold <= 1.0:
            raise ValueError("maker_checker_gap_threshold must be in [0, 1]; " f"got {self.maker_checker_gap_threshold}")


# ---- Arbiter --------------------------------------------------------------


@dataclass
class Arbiter:
    """Decides :class:`MergeResult` from M4 + LLM + Maker inputs.

    Stateless — only :attr:`config` matters. Construct once and reuse.
    """

    config: ArbiterConfig = field(default_factory=ArbiterConfig)

    def resolve(
        self,
        *,
        candidate_id: str = "",
        m4: CheckerVerdict,
        llm: Verdict,
        maker: Optional[Proposal] = None,
    ) -> MergeResult:
        """Resolve one candidate into a :class:`MergeResult`.

        The decision tree is documented at the module top.
        ``candidate_id`` is currently unused inside the merge but is
        accepted for symmetry with the per-candidate audit trail.
        """
        if m4.decision not in VALID_M4:
            raise ValueError(f"unknown m4 decision {m4.decision!r}; expected one of " f"{VALID_M4}")

        maker_score = maker.self_score.self_score if maker is not None else 0.5
        checker_score = llm.checker_score
        gap = abs(maker_score - checker_score)
        final_score = self.config.maker_weight * maker_score + self.config.checker_weight * checker_score

        triggers: list[str] = [f"m4_{m4.decision}"]

        # 1. M4 hard constraint.
        if m4.decision == "rejected":
            return _merge(
                "rejected",
                final_score,
                m4.decision,
                triggers + ["m4_rejected_hard_constraint"],
                checker_confidence=llm.confidence,
                checker_flags=llm.flags,
                agreement=gap <= self.config.maker_checker_gap_threshold,
            )

        llm_accept = llm.accept

        # 2 + 3. M4 promising.
        if m4.decision == "promising":
            if llm_accept:
                # 6. Gap trigger before accepting.
                if gap > self.config.maker_checker_gap_threshold:
                    return _merge(
                        "suspicious_to_human",
                        final_score,
                        m4.decision,
                        triggers + ["llm_accept", "maker_checker_gap"],
                        checker_confidence=llm.confidence,
                        checker_flags=llm.flags,
                        agreement=False,
                    )
                return _merge(
                    "accepted",
                    final_score,
                    m4.decision,
                    triggers + ["llm_accept"],
                    checker_confidence=llm.confidence,
                    checker_flags=llm.flags,
                    agreement=True,
                )
            return _merge(
                "rejected",
                final_score,
                m4.decision,
                triggers + ["llm_reject_overrides"],
                checker_confidence=llm.confidence,
                checker_flags=llm.flags,
                agreement=gap <= self.config.maker_checker_gap_threshold,
            )

        # 4 + 5. M4 suspicious.
        if llm_accept:
            return _merge(
                "suspicious_to_human",
                final_score,
                m4.decision,
                triggers + ["m4_suspicious", "llm_accept"],
                checker_confidence=llm.confidence,
                checker_flags=llm.flags,
                agreement=False,
            )
        return _merge(
            "rejected",
            final_score,
            m4.decision,
            triggers + ["m4_suspicious", "llm_reject"],
            checker_confidence=llm.confidence,
            checker_flags=llm.flags,
            agreement=gap <= self.config.maker_checker_gap_threshold,
        )


def _merge(
    final_decision: str,
    final_score: float,
    m4_verdict: str,
    trigger_reasons: list[str],
    *,
    checker_confidence: Optional[float],
    checker_flags: tuple[dict, ...] = (),
    agreement: Optional[bool] = None,
) -> MergeResult:
    """Build a :class:`MergeResult` with validation."""
    return make_merge_result(
        final_decision=final_decision,
        final_score=final_score,
        m4_verdict=m4_verdict,
        trigger_reasons=trigger_reasons,
        checker_confidence=checker_confidence,
        checker_flags=checker_flags,
        agreement=agreement,
    )


# ---- Back-compat helper for Pareto ----------------------------------------


def pareto_score(
    merge: MergeResult,
    *,
    base_metrics: dict[str, float],
) -> dict[str, float | None]:
    """Compose a 5-D Pareto score from a MergeResult + raw metrics.

    Returns a dict with keys:
        ``sharpe``, ``calmar``, ``profit_factor``,
        ``worst_regime_sharpe``, ``checker_confidence``.

    The legacy 4-D points have ``checker_confidence = None`` and are
    treated as ``-inf`` in the existing Pareto code.
    """
    return {
        "sharpe": float(base_metrics.get("sharpe", 0.0) or 0.0),
        "calmar": float(base_metrics.get("calmar", 0.0) or 0.0),
        "profit_factor": float(base_metrics.get("profit_factor", 0.0) or 0.0),
        "worst_regime_sharpe": float(base_metrics.get("worst_regime_sharpe", 0.0) or 0.0),
        "checker_confidence": merge.checker_confidence,
    }


def is_5d_backcompat(point: dict[str, Any]) -> bool:
    """Return True if ``point`` is a legacy 4-D Pareto point.

    Legacy points are identified by ``checker_confidence`` being ``None``
    or absent. Used by tests to verify the back-compat invariant
    (audit §2.6).
    """
    return point.get("checker_confidence") is None


# ---- Convenience ----------------------------------------------------------


def resolve(
    *,
    candidate_id: str = "",
    m4: CheckerVerdict,
    llm: Verdict,
    maker: Optional[Proposal] = None,
    config: Optional[ArbiterConfig] = None,
) -> MergeResult:
    """Convenience wrapper that constructs a default :class:`Arbiter`."""
    arbiter = Arbiter(config=config or ArbiterConfig())
    return arbiter.resolve(
        candidate_id=candidate_id,
        m4=m4,
        llm=llm,
        maker=maker,
    )


__all__ = [
    "ArbiterConfig",
    "Arbiter",
    "resolve",
    "pareto_score",
    "is_5d_backcompat",
]
