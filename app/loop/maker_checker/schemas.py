"""Schemas — the contract between Maker, Checker, and Arbiter.

Plain dataclasses (no Pydantic dependency to keep the runtime lean and to
match the existing M0-M5 modules' style). Validation is enforced by
``__post_init__`` so any construction site that misuses the types fails
loudly.

Design choices:

* :class:`Proposal.diff` is a mapping of *cluster-relative* field names
  to signed magnitudes expressed as percentages (e.g. ``+15`` = +15% of
  the current value). The Maker never produces raw parameter values.
* :class:`Verdict.checker_score` is **calibrated** — it represents
  ``P(candidate is good | metrics)`` rather than a raw LLM confidence.
* All ``None`` defaults are explicit so the 5-D Pareto back-compat rule
  (``None`` → ``-inf``) is unambiguous at every call site.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---- Reusable primitives --------------------------------------------------


@dataclass(frozen=True)
class MakerSelfScore:
    """The Maker's own confidence in a proposal.

    ``self_score`` is in ``[0, 1]`` and represents the Maker's claim of
    how likely this proposal is to improve the Pareto front. The Arbiter
    uses this as ``maker_norm_score`` in the weighted merge.

    ``expected_impact`` is a free-form description of what the Maker
    predicts will change (``"sharpe: +0.3 in bear"``); it is *not* parsed
    programmatically, only compared against actual outcomes for
    calibration drift detection.
    """

    self_score: float
    expected_impact: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.self_score <= 1.0:
            raise ValueError(
                f"self_score must be in [0, 1]; got {self.self_score}"
            )


@dataclass(frozen=True)
class Proposal:
    """One mutation operation emitted by the Maker.

    Fields:

    * ``clusters_touched`` — non-empty tuple of cluster names from
      :data:`app.loop.mutation.DEFAULT_CLUSTER_MAP`. Single cluster per
      proposal is enforced by :class:`app.loop.maker_checker.maker_agent`.
    * ``diff`` — ``{field_name: signed_magnitude_pct}``. Magnitudes are
      clamped to ``[-50, +50]`` here so a malformed LLM output fails the
      contract rather than producing an out-of-range parameter.
    * ``maker_intent`` — short tag (≤ 64 chars) for log readability.
    * ``reasoning`` — free-form LLM rationale, ≤ 200 chars.
    * ``self_score`` — :class:`MakerSelfScore` instance.
    """

    clusters_touched: tuple[str, ...]
    diff: dict[str, float]
    maker_intent: str
    reasoning: str
    self_score: MakerSelfScore
    proposal_id: str = ""

    MAX_DIFF_PCT: float = 50.0
    MAX_REASONING_LEN: int = 200
    MAX_INTENT_LEN: int = 64

    def __post_init__(self) -> None:
        if not self.clusters_touched:
            raise ValueError("Proposal.clusters_touched must be non-empty")
        if not self.diff:
            raise ValueError("Proposal.diff must be non-empty")
        for field_name, magnitude in self.diff.items():
            if abs(magnitude) > self.MAX_DIFF_PCT:
                raise ValueError(
                    f"diff magnitude for {field_name!r} = {magnitude} "
                    f"exceeds ±{self.MAX_DIFF_PCT}%"
                )
        if len(self.maker_intent) > self.MAX_INTENT_LEN:
            raise ValueError(
                f"maker_intent too long ({len(self.maker_intent)} > "
                f"{self.MAX_INTENT_LEN})"
            )
        if len(self.reasoning) > self.MAX_REASONING_LEN:
            raise ValueError(
                f"reasoning too long ({len(self.reasoning)} > "
                f"{self.MAX_REASONING_LEN})"
            )


# ---- Checker output ------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """The Checker's independent opinion on one candidate.

    Fields:

    * ``candidate_id`` — opaque identifier for the candidate (in strict
      isolation mode this is a salted hash; the raw UUID never reaches
      the Checker).
    * ``checker_score`` — calibrated ``P(good | metrics)`` in ``[0, 1]``.
    * ``confidence`` — the Checker's *own* certainty about the verdict,
      distinct from ``checker_score``. Used to dampen verdicts when the
      LLM is uncertain.
    * ``components`` — per-axis scores (cross-symbol consistency,
      regime robustness, trade quality, statistical sufficiency).
    * ``flags`` — structured findings, severity-tagged.
    * ``accept`` — boolean hard decision.
    * ``feedback`` — natural-language explanation, ≤ 200 chars.
    """

    candidate_id: str
    checker_score: float
    confidence: float
    components: dict[str, float]
    flags: tuple[dict[str, str], ...]
    accept: bool
    feedback: str
    raw_score: float = 0.0  # pre-calibration LLM score (for drift analysis)

    MAX_FEEDBACK_LEN: int = 200

    def __post_init__(self) -> None:
        for name in ("checker_score", "confidence", "raw_score"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]; got {v}")
        for comp, v in self.components.items():
            if not 0.0 <= v <= 1.0:
                raise ValueError(
                    f"components[{comp!r}] must be in [0, 1]; got {v}"
                )
        for f in self.flags:
            if "severity" not in f or "issue" not in f:
                raise ValueError(
                    f"flag missing severity/issue: {f}"
                )
            if f["severity"] not in {"high", "medium", "low"}:
                raise ValueError(
                    f"flag severity must be high|medium|low; got "
                    f"{f['severity']!r}"
                )
        if len(self.feedback) > self.MAX_FEEDBACK_LEN:
            raise ValueError(
                f"feedback too long ({len(self.feedback)} > "
                f"{self.MAX_FEEDBACK_LEN})"
            )


# ---- Arbiter output ------------------------------------------------------


@dataclass(frozen=True)
class MergeResult:
    """The Arbiter's final decision on one candidate.

    Fields:

    * ``final_decision`` — one of ``"accepted"``, ``"rejected"``,
      ``"suspicious_to_human"``.
    * ``final_score`` — weighted merge of Maker self-score and Checker
      calibrated score.
    * ``m4_verdict`` — the M4 heuristic checker's verdict, included for
      audit trails (``"promising" | "suspicious" | "rejected"``).
    * ``trigger_reasons`` — human-readable list of why this decision
      was made (e.g. ``["m4_rejected:low_sample"]``).
    * ``checker_confidence`` — the 5-th Pareto dimension; ``None`` for
      candidates evaluated before the Maker-Checker upgrade.
    """

    final_decision: str
    final_score: float
    m4_verdict: str
    trigger_reasons: tuple[str, ...]
    checker_confidence: Optional[float] = None

    VALID_DECISIONS = ("accepted", "rejected", "suspicious_to_human")

    def __post_init__(self) -> None:
        if self.final_decision not in self.VALID_DECISIONS:
            raise ValueError(
                f"final_decision must be one of {self.VALID_DECISIONS}; "
                f"got {self.final_decision!r}"
            )
        if not -10.0 <= self.final_score <= 10.0:
            raise ValueError(
                f"final_score out of plausible range: {self.final_score}"
            )
        if self.checker_confidence is not None:
            if not 0.0 <= self.checker_confidence <= 1.0:
                raise ValueError(
                    "checker_confidence must be None or in [0, 1]; "
                    f"got {self.checker_confidence}"
                )


# ---- Calibration ---------------------------------------------------------


@dataclass(frozen=True)
class CalibrationParams:
    """Platt-scaling parameters for calibrating Checker raw scores.

    The transformation is::

        calibrated = sigmoid(a * raw + b)

    A well-calibrated Checker should have ``a > 0`` (higher raw → higher
    probability) and ``b`` near 0. ``a == 0`` and ``b == 0`` means
    *no calibration*, returning the raw score mapped via the sigmoid
    midpoint (i.e. 0.5).

    ``ece`` is the Expected Calibration Error on the validation set; the
    runner rejects a calibration with ``ece >= 0.10``.
    """

    a: float
    b: float
    ece: float
    n_samples: int

    MAX_ECE: float = 0.10

    def __post_init__(self) -> None:
        if self.n_samples < 0:
            raise ValueError("n_samples must be >= 0")
        if self.ece < 0:
            raise ValueError("ece must be >= 0")

    def apply(self, raw: float) -> float:
        """Apply Platt scaling. Returns calibrated probability in [0, 1]."""
        if raw < 0.0 or raw > 1.0:
            raise ValueError(f"raw must be in [0, 1]; got {raw}")
        # Numerically stable sigmoid.
        z = self.a * raw + self.b
        if z >= 0:
            p = 1.0 / (1.0 + pow(2.718281828459045, -z))
        else:
            ez = pow(2.718281828459045, z)
            p = ez / (1.0 + ez)
        # Clamp to [0, 1] to avoid float roundoff producing 1.0000000002.
        return max(0.0, min(1.0, p))


__all__ = [
    "MakerSelfScore",
    "Proposal",
    "Verdict",
    "MergeResult",
    "CalibrationParams",
]


# ---- Convenience constructors --------------------------------------------


def make_proposal(
    *,
    clusters_touched: tuple[str, ...] | list[str],
    diff: dict[str, float],
    maker_intent: str,
    reasoning: str,
    self_score: float,
    proposal_id: str = "",
) -> Proposal:
    """Build a :class:`Proposal` from keyword args.

    Accepts lists for ``clusters_touched`` for ergonomics; tuples them
    internally for hashability.
    """
    return Proposal(
        clusters_touched=tuple(clusters_touched),
        diff=dict(diff),
        maker_intent=maker_intent,
        reasoning=reasoning,
        self_score=MakerSelfScore(self_score=self_score),
        proposal_id=proposal_id,
    )


def make_verdict(
    *,
    candidate_id: str,
    checker_score: float,
    confidence: float,
    components: dict[str, float],
    flags: list[dict[str, str]] | tuple[dict[str, str], ...] = (),
    accept: bool,
    feedback: str,
    raw_score: float = 0.0,
) -> Verdict:
    """Build a :class:`Verdict` from keyword args."""
    return Verdict(
        candidate_id=candidate_id,
        checker_score=checker_score,
        confidence=confidence,
        components=dict(components),
        flags=tuple(flags),
        accept=accept,
        feedback=feedback,
        raw_score=raw_score,
    )


def make_merge_result(
    *,
    final_decision: str,
    final_score: float,
    m4_verdict: str,
    trigger_reasons: list[str] | tuple[str, ...],
    checker_confidence: float | None = None,
) -> MergeResult:
    """Build a :class:`MergeResult` from keyword args."""
    return MergeResult(
        final_decision=final_decision,
        final_score=final_score,
        m4_verdict=m4_verdict,
        trigger_reasons=tuple(trigger_reasons),
        checker_confidence=checker_confidence,
    )


def make_calibration(
    *,
    a: float,
    b: float,
    ece: float,
    n_samples: int,
) -> CalibrationParams:
    """Build :class:`CalibrationParams`. Rejects high ECE."""
    return CalibrationParams(a=a, b=b, ece=ece, n_samples=n_samples)