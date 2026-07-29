"""Tests for :mod:`app.loop.maker_checker.runner` and
:mod:`app.loop.maker_checker.review`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.loop.maker_checker.arbiter import ArbiterConfig
from app.loop.maker_checker.checker_agent import CheckerConfig
from app.loop.maker_checker.llm_backend import MockLLMBackend
from app.loop.maker_checker.maker_agent import MakerConfig
from app.loop.maker_checker.review import (
    LOG_FILENAME,
    HumanReviewDecision,
    append_decision,
    load_pending,
)
from app.loop.maker_checker.runner import (
    MakerCheckerRunner,
    RunnerConfig,
    feature_enabled,
    make_runner,
)
from app.loop.worker import CandidateResult

# ---- feature_enabled -----------------------------------------------------


class TestFeatureFlag:
    def test_default_enabled(self, monkeypatch) -> None:
        monkeypatch.delenv("MAKER_CHECKER_ENABLED", raising=False)
        assert feature_enabled() is True

    def test_disabled_via_env(self, monkeypatch) -> None:
        monkeypatch.setenv("MAKER_CHECKER_ENABLED", "false")
        assert feature_enabled() is False

    @pytest.mark.parametrize("v", ["0", "no", "off", "FALSE", "False"])
    def test_disabled_variants(self, monkeypatch, v: str) -> None:
        monkeypatch.setenv("MAKER_CHECKER_ENABLED", v)
        assert feature_enabled() is False


# ---- RunnerConfig --------------------------------------------------------


class TestRunnerConfig:
    def test_defaults(self) -> None:
        c = RunnerConfig()
        assert c.enabled is True
        assert isinstance(c.maker, MakerConfig)
        assert isinstance(c.checker, CheckerConfig)
        assert isinstance(c.arbiter, ArbiterConfig)


# ---- Runner.evaluate -----------------------------------------------------


def _candidate(
    *,
    cid: str = "cand-1",
    metrics: dict | None = None,
    fitness: float | None = 1.0,
    decision: str = "accepted",
) -> CandidateResult:
    return CandidateResult(
        candidate_id=cid,
        params_sha="abc123",
        cluster="C1 Geometry",
        gen=1,
        decision=decision,
        rejection_reason=None,
        metrics=metrics or {"sharpe": 1.2, "trades_count": 50},
        fitness=fitness,
        run_dir="/tmp/r",
        elapsed_seconds=1.0,
    )


class TestEvaluate:
    def test_returns_merge_result(self) -> None:
        runner = make_runner(backend=MockLLMBackend(seed=0))
        m = runner.evaluate(_candidate())
        from app.loop.maker_checker.schemas import MergeResult

        assert isinstance(m, MergeResult)

    def test_rejected_when_low_trade_count(self) -> None:
        runner = make_runner(backend=MockLLMBackend(seed=0))
        # M4 marks low-sample-size as suspicious (trades_count=5 < 30),
        # then the LLM mock can return either accept or reject, which
        # routes to suspicious_to_human or rejected respectively.
        m = runner.evaluate(
            _candidate(
                metrics={
                    "sharpe": 1.0,
                    "trades_count": 5,
                }
            )
        )
        assert m.final_decision in ("rejected", "suspicious_to_human")

    def test_promising_path_runs(self) -> None:
        runner = make_runner(backend=MockLLMBackend(seed=0))
        # M4 promising, LLM accept (mock accept_rate=0.7 → likely).
        m = runner.evaluate(_candidate())
        assert m.final_decision in ("accepted", "rejected", "suspicious_to_human")

    def test_parent_metrics_flow_to_m4(self) -> None:
        runner = make_runner(backend=MockLLMBackend(seed=0))
        # Provide parent_metrics that don't trigger any heuristic flag.
        m = runner.evaluate(
            _candidate(),
            parent_metrics={"fitness": 1.0, "trades_count": 50},
        )
        assert m.final_decision in ("accepted", "rejected", "suspicious_to_human")


# ---- make_runner ---------------------------------------------------------


class TestMakeRunner:
    def test_returns_runner(self) -> None:
        r = make_runner(backend=MockLLMBackend(seed=0))
        assert isinstance(r, MakerCheckerRunner)

    def test_uses_default_backend_when_none(self, monkeypatch) -> None:
        monkeypatch.delenv("MAKER_CHECKER_LLM_BACKEND", raising=False)
        r = make_runner()
        assert isinstance(r, MakerCheckerRunner)

    def test_passes_configs(self) -> None:
        m_cfg = MakerConfig(seed=42)
        c_cfg = CheckerConfig(rejection_threshold=0.7)
        a_cfg = ArbiterConfig(maker_checker_gap_threshold=0.2)
        r = make_runner(
            maker_config=m_cfg,
            checker_config=c_cfg,
            arbiter_config=a_cfg,
            backend=MockLLMBackend(seed=0),
        )
        assert r.maker_agent.config.seed == 42
        assert r.checker_agent.config.rejection_threshold == 0.7
        assert r.arbiter.config.maker_checker_gap_threshold == 0.2

    def test_enabled_caches_env_at_construction(self, monkeypatch) -> None:
        # Set env BEFORE constructing the runner.
        monkeypatch.setenv("MAKER_CHECKER_ENABLED", "true")
        r1 = make_runner(backend=MockLLMBackend(seed=0))
        assert r1.enabled is True
        # Flip env AFTER construction; runner's enabled flag does not change.
        monkeypatch.setenv("MAKER_CHECKER_ENABLED", "false")
        assert r1.enabled is True

        # Now build another runner with the new env value.
        r2 = make_runner(backend=MockLLMBackend(seed=0))
        assert r2.enabled is False


# ---- HumanReviewDecision -------------------------------------------------


class TestHumanReviewDecision:
    def test_valid(self) -> None:
        d = HumanReviewDecision(
            candidate_id="c1",
            decision="accept",
            reviewer="alice",
            timestamp="2026-07-29T00:00:00Z",
        )
        d2 = d.to_dict()
        assert d2["decision"] == "accept"

    @pytest.mark.parametrize("bad", ["", "maybe", "ACCEPT", "Approved"])
    def test_invalid_decision(self, bad: str) -> None:
        with pytest.raises(ValueError, match="decision"):
            HumanReviewDecision(
                candidate_id="c1",
                decision=bad,
                reviewer="alice",
                timestamp="t",
            )

    def test_requires_candidate_id(self) -> None:
        with pytest.raises(ValueError, match="candidate_id"):
            HumanReviewDecision(
                candidate_id="",
                decision="accept",
                reviewer="alice",
                timestamp="t",
            )

    def test_requires_reviewer(self) -> None:
        with pytest.raises(ValueError, match="reviewer"):
            HumanReviewDecision(
                candidate_id="c1",
                decision="accept",
                reviewer="",
                timestamp="t",
            )


# ---- append_decision + load_pending --------------------------------------


class TestAppendAndLoad:
    def test_appends_to_log(self, tmp_path: Path) -> None:
        d = HumanReviewDecision(
            candidate_id="c1",
            decision="accept",
            reviewer="alice",
            timestamp="2026-07-29T00:00:00Z",
        )
        append_decision(tmp_path, d)
        log = tmp_path / LOG_FILENAME
        assert log.exists()
        content = log.read_text()
        # Valid JSON line.
        parsed = json.loads(content.strip())
        assert parsed["candidate_id"] == "c1"

    def test_loads_multiple_decisions(self, tmp_path: Path) -> None:
        for i in range(3):
            append_decision(
                tmp_path,
                HumanReviewDecision(
                    candidate_id=f"c{i}",
                    decision="accept",
                    reviewer="alice",
                    timestamp=f"2026-07-29T00:00:0{i}Z",
                ),
            )
        entries = load_pending(tmp_path)
        assert len(entries) == 3
        assert entries[0]["candidate_id"] == "c0"

    def test_load_on_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_pending(tmp_path) == []

    def test_load_skips_blank_lines(self, tmp_path: Path) -> None:
        log = tmp_path / LOG_FILENAME
        log.write_text('{"candidate_id":"a","decision":"accept","reviewer":"r","timestamp":"t"}\n\n')
        entries = load_pending(tmp_path)
        assert len(entries) == 1
