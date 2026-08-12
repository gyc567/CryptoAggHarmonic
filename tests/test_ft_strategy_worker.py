"""Tests for FT Strategy worker stub (Phase 5).

Worker is intentionally a stub (no real RQ/MCP integration yet). Tests
verify: queue validation, dry-run vs live behavior, payload parsing,
CLI invocation, success/failure result tuples.
"""

from __future__ import annotations

import json

import pytest

from workers.ft_strategy_worker import (
    FTStrategyWorker,
    WorkerJob,
    WorkerResult,
    main,
    parse_args,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _job(queue="ft_hyperopt", job_id="job-1", strategy_id="strat-x"):
    return WorkerJob(
        queue=queue,
        job_id=job_id,
        strategy_id=strategy_id,
        payload={"params": {"epochs": 100}},
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_supported_queues(self):
        expected = ("ft_strategy_create", "ft_hyperopt", "ft_backtest", "ft_analyze")
        assert FTStrategyWorker.SUPPORTED_QUEUES == expected


# ---------------------------------------------------------------------------
# Process
# ---------------------------------------------------------------------------


class TestProcessDryRun:
    def test_dry_run_marks_ok(self):
        w = FTStrategyWorker(dry_run=True)
        result = w.process(_job())
        assert result.ok
        assert result.queue == "ft_hyperopt"
        assert result.job_id == "job-1"

    def test_dry_run_each_supported_queue(self):
        for q in FTStrategyWorker.SUPPORTED_QUEUES:
            r = FTStrategyWorker(dry_run=True).process(_job(queue=q))
            assert r.ok
            assert r.queue == q

    def test_dry_run_does_not_require_payload(self):
        w = FTStrategyWorker(dry_run=True)
        r = w.process(_job())  # payload has only "params"
        assert r.ok


class TestProcessFailures:
    def test_unknown_queue_rejected(self):
        w = FTStrategyWorker(dry_run=True)
        r = w.process(_job(queue="not-a-queue"))
        assert not r.ok
        assert "unknown queue" in r.detail

    def test_non_worker_job_rejected(self):
        w = FTStrategyWorker(dry_run=True)
        r = w.process({"not": "a job"})  # type: ignore[arg-type]
        assert not r.ok
        assert "WorkerJob" in r.detail

    def test_live_mode_returns_failure(self):
        w = FTStrategyWorker(dry_run=False)
        r = w.process(_job())
        assert not r.ok
        assert "live" in r.detail.lower()


class TestWorkerQueueNames:
    def test_queue_names_returns_tuple(self):
        w = FTStrategyWorker()
        names = w.queue_names()
        assert isinstance(names, tuple)
        assert len(names) == 4


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_parse_args_minimum_required(self):
        ns = parse_args([
            "--queue", "ft_hyperopt",
            "--job-id", "j1",
            "--strategy-id", "s1",
        ])
        assert ns.queue == "ft_hyperopt"
        assert ns.job_id == "j1"
        assert ns.strategy_id == "s1"
        assert ns.dry_run is True  # default

    def test_parse_args_live_overrides_dry_run(self):
        ns = parse_args([
            "--queue", "ft_backtest",
            "--job-id", "j2",
            "--strategy-id", "s2",
            "--live",
        ])
        assert ns.dry_run is False

    def test_parse_args_payload_default(self):
        ns = parse_args([
            "--queue", "ft_analyze",
            "--job-id", "j3",
            "--strategy-id", "s3",
        ])
        assert ns.payload_json == "{}"

    def test_parse_args_custom_payload(self):
        ns = parse_args([
            "--queue", "ft_hyperopt",
            "--job-id", "j4",
            "--strategy-id", "s4",
            "--payload-json", '{"epochs": 50}',
        ])
        # parser stores the raw string; main() does json.loads
        assert "epochs" in ns.payload_json

    def test_parse_args_missing_required_fails(self):
        with pytest.raises(SystemExit):
            parse_args(["--queue", "ft_hyperopt"])  # missing job-id, strategy-id


class TestMainFunction:
    def test_main_dry_run_success(self, capfd):
        exit_code = main([
            "--queue", "ft_hyperopt",
            "--job-id", "cli-1",
            "--strategy-id", "cli-strat",
            "--payload-json", '{"k":"v"}',
        ])
        assert exit_code == 0
        captured = capfd.readouterr()
        body = json.loads(captured.out.strip())
        assert body["ok"] is True
        assert body["queue"] == "ft_hyperopt"
        assert body["job_id"] == "cli-1"

    def test_main_unknown_queue_returns_1(self):
        # argparse exits 2 for invalid choice; not a worker failure
        with pytest.raises(SystemExit) as exc:
            main([
                "--queue", "bogus",
                "--job-id", "x",
                "--strategy-id", "y",
            ])
        assert exc.value.code == 2

    def test_main_bad_json_returns_2(self):
        exit_code = main([
            "--queue", "ft_hyperopt",
            "--job-id", "x",
            "--strategy-id", "y",
            "--payload-json", "not json {",
        ])
        assert exit_code == 2


# ---------------------------------------------------------------------------
# Immutability + structural
# ---------------------------------------------------------------------------


class TestWorkerResultFields:
    def test_result_dataclass(self):
        r = WorkerResult(ok=True, queue="x", job_id="y")
        assert r.ok
        assert r.queue == "x"
        assert r.job_id == "y"
        assert r.detail == ""
