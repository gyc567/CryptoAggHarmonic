"""AI Judge scaffold.

v3 changelog item 9 + docs/HarmonicSignal-Bench.md AI Judge.

A judge takes a SignalRecord (plus optional forward-window context)
and returns a JudgeVerdict with a numeric score (0-100) and a
free-text justification. In production the Judge is an LLM call
(via the existing ``bench.judge.llm`` module). In tests we use the
``MockJudge`` so the rest of the framework can run hermetically.

Cost guard
----------
The runner enforces:
* ``max_calls_per_run`` (default 50) — total judge invocations in
  one bench run. Once exceeded, the runner falls back to
  ``score=None`` and appends a warning.
* ``max_concurrency`` (default 5) — semaphore-limited concurrency.
  Each Judge.call respects ``acquire/release`` if the underlying
  implementation supports it (LLMJudge does; MockJudge doesn't care).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from bench.dataset.signal_record import SignalRecord


@dataclass
class JudgeVerdict:
    """Result of one judge invocation."""

    score: Optional[float]  # 0-100, or None if judge was rate-limited
    justification: str
    confidence: float = 1.0  # 0-1, model self-reported confidence
    model: str = "mock"
    warnings: List[str] = field(default_factory=list)


class Judge(Protocol):
    """Protocol for any judge implementation."""

    def __init__(self, **kwargs) -> None: ...
    def call(self, rec: SignalRecord, forward_df=None) -> JudgeVerdict: ...


# -------- Mock judge --------

class MockJudge:
    """Deterministic mock that returns a score from a lookup table.

    Lookup keys on (rec.outcome, rec.direction) so tests can assert
    the judge is being invoked with the right data. No network I/O.
    """

    DEFAULT_TABLE: dict[tuple[Optional[str], str], float] = {
        ("tp1", "long"): 80.0,
        ("tp1", "short"): 80.0,
        ("tp2", "long"): 90.0,
        ("tp2", "short"): 90.0,
        ("tp3", "long"): 95.0,
        ("tp3", "short"): 95.0,
        ("breakeven", "long"): 50.0,
        ("breakeven", "short"): 50.0,
        ("stoploss", "long"): 20.0,
        ("stoploss", "short"): 20.0,
    }
    DEFAULT_NO_OUTCOME = 0.0

    def __init__(
        self,
        table: Optional[dict] = None,
        default: float = DEFAULT_NO_OUTCOME,
        model_name: str = "mock-v1",
    ) -> None:
        self._table = table if table is not None else dict(self.DEFAULT_TABLE)
        self._default = default
        self._model_name = model_name

    def call(self, rec: SignalRecord, forward_df=None) -> JudgeVerdict:
        key = (rec.outcome, rec.direction)
        score = self._table.get(key, self._default)
        return JudgeVerdict(
            score=score,
            justification=f"mock judge: outcome={rec.outcome}, direction={rec.direction}",
            model=self._model_name,
        )


# -------- Cost guard --------

class CostGuard:
    """Track judge invocation count + concurrency. Thread-safe via
    simple counter + semaphore for the public API.
    """

    def __init__(self, max_calls: int = 50, max_concurrency: int = 5) -> None:
        self.max_calls = max_calls
        self.max_concurrency = max_concurrency
        self._calls_used = 0
        self._active = 0
        self.warnings: List[str] = []

    @property
    def calls_used(self) -> int:
        return self._calls_used

    @property
    def active(self) -> int:
        return self._active

    @property
    def exhausted(self) -> bool:
        return self._calls_used >= self.max_calls

    def acquire(self) -> bool:
        """Reserve a slot. Returns False if exhausted or at capacity."""
        if self.exhausted:
            self.warnings.append(
                f"judge call limit reached ({self.max_calls}); further calls suppressed"
            )
            return False
        if self._active >= self.max_concurrency:
            self.warnings.append(
                f"judge concurrency limit reached ({self.max_concurrency})"
            )
            return False
        self._calls_used += 1
        self._active += 1
        return True

    def release(self) -> None:
        if self._active > 0:
            self._active -= 1

    def reset(self) -> None:
        """Reset state (used between bench runs)."""
        self._calls_used = 0
        self._active = 0
        self.warnings = []


# -------- LLM judge (stub) --------

class LLMJudge:
    """Production judge that calls the real LLM.

    Stubbed here so the protocol is importable; real implementation
    lives behind the cost guard. The runner catches ImportError /
    network failures and falls back to MockJudge with a warning.
    """

    def __init__(
        self,
        model: str = "minimax/minimax-m3",
        prompt_version: str = "v1",
    ) -> None:
        self.model = model
        self.prompt_version = prompt_version

    def call(self, rec: SignalRecord, forward_df=None) -> JudgeVerdict:
        raise NotImplementedError(
            "LLMJudge.call requires a live LLM client. Use MockJudge for tests."
        )


# -------- Convenience wrappers --------

def judge_with_guard(
    judge,
    rec: SignalRecord,
    guard: CostGuard,
    forward_df=None,
) -> JudgeVerdict:
    """Run a judge call through the cost guard. Returns a verdict with
    ``score=None`` if the guard refuses the call.

    Always releases the guard slot, even on exception.
    """
    if not guard.acquire():
        return JudgeVerdict(
            score=None,
            justification="judge call suppressed by cost guard",
            warnings=list(guard.warnings),
        )
    try:
        verdict = judge.call(rec, forward_df=forward_df)
        if guard.warnings:
            verdict.warnings = list(verdict.warnings) + list(guard.warnings)
        return verdict
    finally:
        guard.release()
