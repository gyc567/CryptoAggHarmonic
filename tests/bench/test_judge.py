"""Tests for bench.judge.mock."""

from __future__ import annotations

import pytest

from bench.dataset.signal_record import empty_record
from bench.judge.mock import (
    CostGuard,
    JudgeVerdict,
    LLMJudge,
    MockJudge,
    judge_with_guard,
)


def _rec(*, outcome: str | None = "tp1", direction: str = "long"):
    return empty_record(direction=direction, outcome=outcome)


# ---------- MockJudge ----------

def test_mock_judge_default_table() -> None:
    j = MockJudge()
    v = j.call(_rec(outcome="tp1", direction="long"))
    assert v.score == 80.0
    assert "mock judge" in v.justification
    assert v.model == "mock-v1"


def test_mock_judge_tp3_short() -> None:
    j = MockJudge()
    v = j.call(_rec(outcome="tp3", direction="short"))
    assert v.score == 95.0


def test_mock_judge_stoploss_long() -> None:
    j = MockJudge()
    v = j.call(_rec(outcome="stoploss", direction="long"))
    assert v.score == 20.0


def test_mock_judge_breakeven() -> None:
    j = MockJudge()
    v = j.call(_rec(outcome="breakeven", direction="short"))
    assert v.score == 50.0


def test_mock_judge_unknown_outcome_uses_default() -> None:
    j = MockJudge()
    v = j.call(_rec(outcome="mystery"))
    assert v.score == 0.0


def test_mock_judge_no_outcome_uses_default() -> None:
    j = MockJudge()
    v = j.call(_rec(outcome=None))
    assert v.score == 0.0


def test_mock_judge_custom_table() -> None:
    custom = {("tp1", "long"): 42.0}
    j = MockJudge(table=custom)
    v = j.call(_rec(outcome="tp1", direction="long"))
    assert v.score == 42.0


def test_mock_judge_custom_default() -> None:
    j = MockJudge(default=99.0)
    v = j.call(_rec(outcome="mystery"))
    assert v.score == 99.0


def test_mock_judge_custom_model_name() -> None:
    j = MockJudge(model_name="custom-v3")
    v = j.call(_rec(outcome="tp1", direction="long"))
    assert v.model == "custom-v3"


def test_mock_judge_table_isolated_per_instance() -> None:
    """Mutating one instance's table must not affect another."""
    j1 = MockJudge()
    j2 = MockJudge()
    j1._table["custom_key"] = 1.0
    assert "custom_key" not in j2._table


# ---------- JudgeVerdict ----------

def test_verdict_defaults() -> None:
    v = JudgeVerdict(score=50.0, justification="x")
    assert v.score == 50.0
    assert v.justification == "x"
    assert v.confidence == 1.0
    assert v.model == "mock"
    assert v.warnings == []


def test_verdict_can_be_constructed_with_warnings() -> None:
    v = JudgeVerdict(score=10.0, justification="x", warnings=["w1", "w2"])
    assert v.warnings == ["w1", "w2"]


def test_verdict_score_can_be_none() -> None:
    v = JudgeVerdict(score=None, justification="rate-limited")
    assert v.score is None


# ---------- LLMJudge (stub) ----------

def test_llm_judge_call_raises() -> None:
    j = LLMJudge()
    with pytest.raises(NotImplementedError):
        j.call(_rec())


def test_llm_judge_default_model() -> None:
    j = LLMJudge()
    assert j.model == "minimax/minimax-m3"
    assert j.prompt_version == "v1"


def test_llm_judge_custom_model() -> None:
    j = LLMJudge(model="custom", prompt_version="v2")
    assert j.model == "custom"
    assert j.prompt_version == "v2"


# ---------- CostGuard ----------

def test_cost_guard_default_limits() -> None:
    g = CostGuard()
    assert g.max_calls == 50
    assert g.max_concurrency == 5
    assert g.exhausted is False
    assert g.active == 0


def test_cost_guard_acquire_release() -> None:
    g = CostGuard()
    assert g.acquire() is True
    assert g.calls_used == 1
    assert g.active == 1
    g.release()
    assert g.active == 0
    assert g.calls_used == 1  # not reset


def test_cost_guard_exhausts_at_max() -> None:
    g = CostGuard(max_calls=2)
    g.acquire()
    g.acquire()
    assert g.exhausted is True
    assert g.acquire() is False
    assert len(g.warnings) == 1


def test_cost_guard_concurrency_limit() -> None:
    g = CostGuard(max_calls=100, max_concurrency=2)
    assert g.acquire() is True
    assert g.acquire() is True
    assert g.acquire() is False  # capacity
    assert any("concurrency" in w for w in g.warnings)


def test_cost_guard_release_allows_more() -> None:
    g = CostGuard(max_calls=100, max_concurrency=1)
    g.acquire()
    assert g.acquire() is False
    g.release()
    assert g.acquire() is True


def test_cost_guard_release_clamps_at_zero() -> None:
    g = CostGuard()
    g.release()  # nothing active
    g.release()  # still nothing
    assert g.active == 0


def test_cost_guard_reset() -> None:
    g = CostGuard(max_calls=2)
    g.acquire()
    g.acquire()
    g.release()
    g.reset()
    assert g.calls_used == 0
    assert g.active == 0
    assert g.warnings == []
    assert g.exhausted is False


# ---------- judge_with_guard ----------

def test_judge_with_guard_returns_verdict() -> None:
    g = CostGuard()
    j = MockJudge()
    v = judge_with_guard(j, _rec(outcome="tp1"), g)
    assert v.score == 80.0
    assert g.calls_used == 1
    assert g.active == 0  # released


def test_judge_with_guard_returns_none_when_exhausted() -> None:
    g = CostGuard(max_calls=0)
    j = MockJudge()
    v = judge_with_guard(j, _rec(outcome="tp1"), g)
    assert v.score is None
    assert "rate-limited" in v.justification.lower() or "suppressed" in v.justification


def test_judge_with_guard_releases_on_exception() -> None:
    g = CostGuard()

    class ExplodingJudge:
        def call(self, rec, forward_df=None):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        judge_with_guard(ExplodingJudge(), _rec(), g)
    assert g.active == 0


def test_judge_with_guard_collects_warning() -> None:
    g = CostGuard(max_calls=1)
    g.acquire()
    # g is now exhausted
    j = MockJudge()
    v = judge_with_guard(j, _rec(), g)
    assert v.score is None
    assert len(v.warnings) > 0


def test_judge_with_guard_appends_persisted_guard_warnings() -> None:
    """If the guard has accumulated warnings from prior calls (e.g.
    concurrency cap), the verdict's warnings list should include them
    so the runner can surface them in the report."""
    g = CostGuard(max_concurrency=1)
    g.acquire()  # holds the only slot
    # The guard.warnings is empty right now (no warning emitted because
    # we successfully acquired). But if a second call attempts acquire
    # and fails, it appends. Simulate that:
    g.acquire()  # this fails and appends "concurrency limit" warning
    g.release()  # release the slot
    # Now guard has 1 warning persisted. A successful call should pick
    # it up.
    j = MockJudge()
    v = judge_with_guard(j, _rec(outcome="tp1"), g)
    assert v.score == 80.0
    assert any("concurrency" in w for w in v.warnings)
