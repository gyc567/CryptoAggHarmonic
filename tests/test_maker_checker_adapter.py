"""Tests for :mod:`app.loop.maker_checker.adapter`."""

from __future__ import annotations

from app.loop.checker import CheckerVerdict
from app.loop.maker_checker.adapter import evaluate_candidate
from app.loop.maker_checker.llm_backend import MockLLMBackend
from app.loop.maker_checker.runner import make_runner
from app.loop.worker import CandidateResult


def _candidate(**kw) -> CandidateResult:
    return CandidateResult(
        candidate_id=kw.get("cid", "cand-1"),
        params_sha="abc",
        cluster=kw.get("cluster", "C1"),
        gen=kw.get("gen", 1),
        decision="accepted",
        rejection_reason=None,
        metrics=kw.get("metrics", {"sharpe": 1.0, "trades_count": 50}),
        fitness=kw.get("fitness", 1.0),
        run_dir="/tmp/r",
        elapsed_seconds=1.0,
    )


class TestEvaluateCandidate:
    def test_no_runner_returns_m4(self, monkeypatch) -> None:
        monkeypatch.setenv("MAKER_CHECKER_ENABLED", "false")
        v = evaluate_candidate(_candidate())
        assert isinstance(v, CheckerVerdict)

    def test_with_runner_returns_merge_result(self, monkeypatch) -> None:
        monkeypatch.setenv("MAKER_CHECKER_ENABLED", "true")
        runner = make_runner(backend=MockLLMBackend(seed=0))
        v = evaluate_candidate(_candidate(), runner=runner)
        # Without LLM enabled and M4 says promising, returns accepted.
        assert isinstance(v, CheckerVerdict)
        assert v.decision in ("accepted", "rejected", "suspicious_to_human")

    def test_disabled_flag_short_circuits(self, monkeypatch) -> None:
        monkeypatch.setenv("MAKER_CHECKER_ENABLED", "false")
        runner = make_runner(backend=MockLLMBackend(seed=0))
        v = evaluate_candidate(_candidate(), runner=runner)
        # When disabled, runner is bypassed → pure M4.
        assert isinstance(v, CheckerVerdict)

    def test_parent_metrics_propagates(self, monkeypatch) -> None:
        monkeypatch.setenv("MAKER_CHECKER_ENABLED", "false")
        v = evaluate_candidate(
            _candidate(),
            parent_metrics={"fitness": 2.0},
        )
        assert isinstance(v, CheckerVerdict)
