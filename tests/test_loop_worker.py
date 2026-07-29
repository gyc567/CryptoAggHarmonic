"""Tests for the worker module — exercises the subprocess boundary with a
mocked :func:`subprocess.run` so we don't need the real backtest harness
to validate the wiring.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from app.config.tuning import TUNING
from app.loop.worker import run_candidate


def _write_metrics(run_dir: Path, *, trades: int = 35, sharpe: float = 0.4) -> None:
    metrics = {
        "__aggregate__": {
            "experimental": {
                "trades_count": trades,
                "sharpe": sharpe,
                "calmar": 1.0,
                "profit_factor": 2.0,
            },
        },
        "__meta__": {"fitness": {"experimental": 1.5}},
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics))


def _make_run_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="loop-run-"))


class TestRunCandidate:
    def test_success(self, tmp_path):
        run_dir = _make_run_dir()

        def fake_run(cmd, **kw):
            _write_metrics(run_dir, trades=35, sharpe=0.4)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        with mock.patch("app.loop.worker.subprocess.run", side_effect=fake_run):
            r = run_candidate(
                candidate_id="c1",
                tuning=TUNING,
                symbol_set="BTCUSD",
                quarter=None,
                run_dir=run_dir,
                timeout_seconds=60,
            )

        assert r.decision == "accepted"
        assert r.metrics["trades_count"] == 35
        assert r.fitness == 1.5
        assert r.elapsed_seconds >= 0
        assert (run_dir / "tuning.yaml").exists()
        assert (run_dir / "backtest.log").exists()

    def test_rejected_low_trade_count(self, tmp_path):
        run_dir = _make_run_dir()

        def fake_run(cmd, **kw):
            _write_metrics(run_dir, trades=10)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        with mock.patch("app.loop.worker.subprocess.run", side_effect=fake_run):
            r = run_candidate(
                candidate_id="c1",
                tuning=TUNING,
                symbol_set="BTCUSD",
                quarter=None,
                run_dir=run_dir,
            )

        assert r.decision == "rejected"
        assert "10" in r.rejection_reason

    def test_subprocess_nonzero_exit(self, tmp_path):
        run_dir = _make_run_dir()

        def fake_run(cmd, **kw):
            # Leave no metrics.json.
            return subprocess.CompletedProcess(cmd, 1, b"boom", b"boom")

        with mock.patch("app.loop.worker.subprocess.run", side_effect=fake_run):
            r = run_candidate(
                candidate_id="c1",
                tuning=TUNING,
                symbol_set="BTCUSD",
                quarter=None,
                run_dir=run_dir,
            )

        assert r.decision == "error"
        assert "exit=1" in r.error

    def test_timeout(self, tmp_path):
        run_dir = _make_run_dir()

        def fake_run(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 5)

        with mock.patch("app.loop.worker.subprocess.run", side_effect=fake_run):
            r = run_candidate(
                candidate_id="c1",
                tuning=TUNING,
                symbol_set="BTCUSD",
                quarter=None,
                run_dir=run_dir,
                timeout_seconds=5,
            )

        assert r.decision == "error"
        assert "timed out" in r.error

    def test_accepts_dict_tuning(self, tmp_path):
        run_dir = _make_run_dir()
        d = {f.name: getattr(TUNING, f.name) for f in __import__("dataclasses").fields(TUNING)}

        def fake_run(cmd, **kw):
            _write_metrics(run_dir)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        with mock.patch("app.loop.worker.subprocess.run", side_effect=fake_run):
            r = run_candidate(
                candidate_id="c1",
                tuning=d,
                symbol_set="BTCUSD",
                quarter=None,
                run_dir=run_dir,
            )
        assert r.decision == "accepted"
