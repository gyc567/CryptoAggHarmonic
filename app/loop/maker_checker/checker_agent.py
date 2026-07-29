"""Checker agent — independent LLM verifier with information isolation.

The Checker receives a candidate's *results* (trade ledger, metrics,
regime blobs) and emits a calibrated :class:`Verdict`. Crucially, it
sees none of the Maker's creative-layer metadata — that stripping is
done by :mod:`app.loop.maker_checker.isolation` before this agent is
invoked.

Calibration is applied to the raw LLM score via the configured
:class:`CalibrationParams`. When calibration is unavailable, the raw
score is used directly with a documented ``raw_score == checker_score``
fallback.

Public API:

* :class:`CheckerAgent` — runs :meth:`verify` on a candidate's results.
* :class:`CheckerConfig` — runtime config.
* :func:`verify` — convenience wrapper.

Design constraints (audit §2.5):

* The Checker's verdict is **always** paired with the M4 heuristic
  checker's verdict (audit §1.3, §2.6). This module returns its own
  verdict; the M4 fusion happens in :mod:`arbiter`.
* The agent never raises on backend failure; it returns
  ``accept=False`` with ``confidence=0.0`` so the Arbiter can degrade
  gracefully.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.loop.maker_checker.calibration import calibrate
from app.loop.maker_checker.isolation import (
    MINIMAL,
    MODERATE,
    STRICT,
    strip_maker_artifacts,
)
from app.loop.maker_checker.llm_backend import LLMBackend, MockLLMBackend
from app.loop.maker_checker.schemas import (
    CalibrationParams,
    Verdict,
    make_verdict,
)


logger = logging.getLogger("app.loop.maker_checker.checker_agent")


VALID_ISOLATION_LEVELS = (STRICT, MODERATE, MINIMAL)


# ---- Configuration --------------------------------------------------------


@dataclass(frozen=True)
class CheckerConfig:
    """Static configuration for a :class:`CheckerAgent`.

    Fields:

    * ``isolation_level`` — one of ``"strict" | "moderate" | "minimal"``.
      Default ``"strict"`` (audit §2.7).
    * ``calibration_pairs`` — pre-fitted :class:`CalibrationParams`, or
      ``None`` to use identity calibration (raw score == calibrated).
    * ``rejection_threshold`` — candidates with calibrated score below
      this are marked ``accept=False``. Default ``0.3``.
    * ``min_confidence`` — if the LLM's self-reported confidence is
      below this, the verdict is forced to ``accept=False`` regardless
      of score. Default ``0.0`` (no damping).
    """

    isolation_level: str = STRICT
    calibration_params: CalibrationParams | None = None
    rejection_threshold: float = 0.3
    min_confidence: float = 0.0

    def __post_init__(self) -> None:
        if self.isolation_level not in VALID_ISOLATION_LEVELS:
            raise ValueError(
                f"isolation_level must be one of {VALID_ISOLATION_LEVELS}; "
                f"got {self.isolation_level!r}"
            )
        if not 0.0 <= self.rejection_threshold <= 1.0:
            raise ValueError(
                f"rejection_threshold must be in [0, 1]; got "
                f"{self.rejection_threshold}"
            )
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError(
                f"min_confidence must be in [0, 1]; got "
                f"{self.min_confidence}"
            )


# ---- Agent ---------------------------------------------------------------


@dataclass
class CheckerAgent:
    """Runs :meth:`verify` on a single candidate's results.

    The agent takes ownership of:

    * Isolation (strips Maker artifacts per the configured level).
    * LLM call (delegated to ``backend``).
    * Calibration (via ``config.calibration_params``).
    * Thresholding (``accept = calibrated >= threshold`` and
      ``confidence >= min_confidence``).
    """

    backend: LLMBackend = field(default_factory=MockLLMBackend)
    config: CheckerConfig = field(default_factory=CheckerConfig)
    salt: str = ""

    def _seed_for(self, candidate_id: str) -> int:
        """Derive a deterministic per-candidate seed.

        Two candidates with identical metrics still receive different
        seeds, so the mock backend returns different verdicts and the
        isolation property survives end-to-end tests.
        """
        import hashlib
        h = hashlib.sha256(
            (self.salt + candidate_id).encode("utf-8"),
        ).digest()
        return int.from_bytes(h[:4], "big")

    def verify(
        self,
        candidate_id: str,
        results: dict[str, Any],
    ) -> Verdict:
        """Verify one candidate and return a calibrated verdict.

        ``results`` is the dict produced by the worker subprocess +
        any extra Maker metadata. The agent isolates it according to
        its config before sending to the LLM.
        """
        # 1. Isolate — the agent never sees Maker metadata.
        isolated = strip_maker_artifacts(
            {**results, "candidate_id": candidate_id},
            level=self.config.isolation_level,
            salt=self.salt,
        )

        # 2. Build a deterministic prompt for the LLM.
        prompt = _build_prompt(isolated)

        # 3. Call backend; on failure, return a low-confidence reject.
        # Use a deterministic seed derived from the candidate id so two
        # candidates with identical metrics still receive different
        # prompts and (for the mock backend) different verdicts.
        seed = self._seed_for(candidate_id)
        try:
            raw_out = self.backend.complete_verdict(prompt, seed=seed)
        except Exception as exc:  # noqa: BLE001 — any backend error
            logger.warning("checker backend failed: %s", exc)
            return _low_confidence_reject(candidate_id)

        # 4. Parse + validate.
        verdict = _parse_verdict(candidate_id, raw_out)
        if verdict is None:
            return _low_confidence_reject(candidate_id)

        # 5. Calibrate.
        params = self.config.calibration_params
        if params is None:
            calibrated = verdict.raw_score
        else:
            calibrated = params.apply(verdict.raw_score)

        # 6. Threshold.
        accept = (
            verdict.accept
            and calibrated >= self.config.rejection_threshold
            and verdict.confidence >= self.config.min_confidence
        )

        # 7. Re-emit with calibrated score.
        return make_verdict(
            candidate_id=candidate_id,
            checker_score=calibrated,
            confidence=verdict.confidence,
            components=verdict.components,
            flags=list(verdict.flags),
            accept=accept,
            feedback=verdict.feedback,
            raw_score=verdict.raw_score,
        )


# ---- Helpers --------------------------------------------------------------


def _build_prompt(isolated: dict[str, Any]) -> str:
    """Compose the prompt for the Checker LLM.

    Stable, deterministic format. The :class:`MockLLMBackend` hashes
    this; changing whitespace will break tests.
    """
    keys = sorted(isolated.keys())
    metrics = isolated.get("metrics", {})
    sharpe = metrics.get("sharpe", 0.0)
    trades = metrics.get("trades_count", 0)
    return (
        f"checker|metrics_keys={','.join(sorted(metrics.keys()))}|"
        f"sharpe={sharpe:.3f}|trades={trades}|"
        f"top_keys={','.join(keys[:5])}"
    )


def _parse_verdict(
    candidate_id: str, raw: dict[str, Any]
) -> Verdict | None:
    """Build a :class:`Verdict` from an LLM JSON output, or return None."""
    if not isinstance(raw, dict):
        return None
    score = raw.get("checker_score")
    confidence = raw.get("confidence")
    raw_score = raw.get("raw_score", score)
    components = raw.get("components")
    flags = raw.get("flags") or []
    accept = raw.get("accept")
    feedback = raw.get("feedback", "")
    if not isinstance(score, (int, float)):
        return None
    if not isinstance(confidence, (int, float)):
        return None
    if not isinstance(raw_score, (int, float)):
        raw_score = score
    if not isinstance(components, dict):
        return None
    if not isinstance(flags, list):
        return None
    if not isinstance(accept, bool):
        return None
    if not isinstance(feedback, str):
        return None
    cleaned_flags = []
    for f in flags:
        if (
            isinstance(f, dict)
            and "severity" in f
            and "issue" in f
            and f["severity"] in ("high", "medium", "low")
        ):
            cleaned_flags.append(f)
    try:
        return make_verdict(
            candidate_id=candidate_id,
            checker_score=float(score),
            confidence=float(confidence),
            components={k: float(v) for k, v in components.items()},
            flags=cleaned_flags,
            accept=bool(accept),
            feedback=feedback[: Verdict.MAX_FEEDBACK_LEN],
            raw_score=float(raw_score),
        )
    except (ValueError, TypeError):
        return None


def _low_confidence_reject(candidate_id: str) -> Verdict:
    """Return a canonical "backend failed" verdict."""
    return make_verdict(
        candidate_id=candidate_id,
        checker_score=0.0,
        confidence=0.0,
        components={},
        flags=[{"severity": "high", "issue": "checker_backend_failure"}],
        accept=False,
        feedback="checker backend failure — defaulted to reject",
        raw_score=0.0,
    )


def verify(
    candidate_id: str,
    results: dict[str, Any],
    *,
    config: CheckerConfig | None = None,
    backend: LLMBackend | None = None,
    salt: str = "",
) -> Verdict:
    """Convenience wrapper that constructs a default :class:`CheckerAgent`."""
    agent = CheckerAgent(
        backend=backend or MockLLMBackend(),
        config=config or CheckerConfig(),
        salt=salt,
    )
    return agent.verify(candidate_id, results)


# ---- Calibration helper ---------------------------------------------------


def fit_calibration_from_history(
    history: Sequence[tuple[float, int]],
) -> CalibrationParams | None:
    """Fit Platt scaling on historical (raw_score, true_label) pairs.

    Returns ``None`` if the history is too small or unbalanced. The
    Arbiter uses this opportunistically at startup; if it returns
    ``None`` the Checker falls back to identity calibration.
    """
    if len(history) < 10:
        return None
    try:
        return calibrate(history)
    except ValueError:
        return None


__all__ = [
    "CheckerConfig",
    "CheckerAgent",
    "verify",
    "fit_calibration_from_history",
]