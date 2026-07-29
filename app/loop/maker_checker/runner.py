"""Runner — orchestrator for the Maker-Checker loop.

The runner ties :class:`MakerAgent` → candidate generation →
:class:`CheckerAgent` → :class:`Arbiter` together. It is **not** the
same as :mod:`app.loop.driver`; the driver stays as the existing
single-generation CLI, and the runner is invoked from it (or from
``search.run_generation``) when ``MAKER_CHECKER_ENABLED`` is true.

Feature flag (audit §2.9): ``MAKER_CHECKER_ENABLED=false`` short-
circuits the runner to return the original driver's input unchanged.
This is the rollback lever.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from app.loop.checker import check_candidate
from app.loop.maker_checker.arbiter import (
    Arbiter,
    ArbiterConfig,
)
from app.loop.maker_checker.checker_agent import (
    CheckerAgent,
    CheckerConfig,
)
from app.loop.maker_checker.isolation import make_salt
from app.loop.maker_checker.llm_backend import (
    LLMBackend,
    default_backend,
)
from app.loop.maker_checker.maker_agent import (
    MakerAgent,
    MakerConfig,
)
from app.loop.maker_checker.schemas import MergeResult
from app.loop.worker import CandidateResult

logger = logging.getLogger("app.loop.maker_checker.runner")


# ---- Feature flag ---------------------------------------------------------


def feature_enabled() -> bool:
    """Return True unless the env explicitly disables the subsystem."""
    flag = os.environ.get("MAKER_CHECKER_ENABLED", "true").lower()
    return flag not in ("false", "0", "no", "off")


# ---- Configuration --------------------------------------------------------


@dataclass(frozen=True)
class RunnerConfig:
    """Top-level config that bundles Maker + Checker + Arbiter configs."""

    maker: MakerConfig = field(default_factory=MakerConfig)
    checker: CheckerConfig = field(default_factory=CheckerConfig)
    arbiter: ArbiterConfig = field(default_factory=ArbiterConfig)
    enabled: bool = True

    def __post_init__(self) -> None:
        # Sync the feature flag in case the env is set.
        if not self.enabled:
            return


# ---- Runner ---------------------------------------------------------------


@dataclass
class MakerCheckerRunner:
    """Orchestrates the full Maker → Check → Arbiter flow.

    The runner does not start subprocesses itself; it assumes the
    caller has already obtained :class:`CandidateResult`s (typically
    via ``ProcessPoolExecutor`` + :func:`app.loop.worker.run_candidate`).
    Its job is to fuse the creative side (Maker) with the validation
    side (M4 heuristics + LLM Checker) and the decision side (Arbiter).
    """

    maker_agent: MakerAgent = field(default_factory=MakerAgent)
    checker_agent: CheckerAgent = field(default_factory=CheckerAgent)
    arbiter: Arbiter = field(default_factory=Arbiter)
    salt: str = field(default_factory=make_salt)
    enabled: bool = field(default_factory=feature_enabled)

    def evaluate(
        self,
        candidate: CandidateResult,
        *,
        parent_metrics: Optional[dict[str, Any]] = None,
    ) -> MergeResult:
        """Run M4 + LLM Checker + Arbiter on one :class:`CandidateResult`.

        ``candidate.metrics`` is the dict produced by the v3 backtest
        harness; the M4 checker inspects it for heuristic red flags,
        the LLM Checker receives an isolated version via
        :mod:`app.loop.maker_checker.isolation`.
        """
        # 1. M4 heuristic.
        m4 = check_candidate(candidate, parent_metrics=parent_metrics)

        # 2. LLM Checker on isolated payload.
        llm = self.checker_agent.verify(
            candidate.candidate_id,
            {
                "metrics": candidate.metrics or {},
                "fitness": candidate.fitness,
                "decision": candidate.decision,
                "elapsed_seconds": candidate.elapsed_seconds,
            },
        )

        # 3. Arbiter fuses them. Maker self_score is not available
        # at evaluation time (the proposal has already been realised
        # into a TuningConstants + CandidateResult), so we pass None
        # and the Arbiter falls back to 0.5.
        return self.arbiter.resolve(
            candidate_id=candidate.candidate_id,
            m4=m4,
            llm=llm,
            maker=None,
        )


# ---- Convenience factory --------------------------------------------------


def make_runner(
    *,
    maker_config: Optional[MakerConfig] = None,
    checker_config: Optional[CheckerConfig] = None,
    arbiter_config: Optional[ArbiterConfig] = None,
    backend: Optional[LLMBackend] = None,
    salt: Optional[str] = None,
) -> MakerCheckerRunner:
    """Construct a fully-wired :class:`MakerCheckerRunner`.

    The Maker and Checker share one backend (the LLM provider is one
    billable entity). Calibration is auto-fitted from a labelled
    history blob if supplied; otherwise identity calibration is used.
    """
    if backend is None:
        backend = default_backend()

    return MakerCheckerRunner(
        maker_agent=MakerAgent(
            backend=backend,
            config=maker_config or MakerConfig(),
        ),
        checker_agent=CheckerAgent(
            backend=backend,
            config=checker_config or CheckerConfig(),
            salt=salt or make_salt(),
        ),
        arbiter=Arbiter(config=arbiter_config or ArbiterConfig()),
        salt=salt or make_salt(),
    )


__all__ = [
    "feature_enabled",
    "RunnerConfig",
    "MakerCheckerRunner",
    "make_runner",
]
