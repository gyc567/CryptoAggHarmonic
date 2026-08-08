"""Phase 0 baseline + dry-run pipeline tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.config.tuning import TUNING
from app.loop.baseline import (
    build_baseline_candidates,
    run_baseline,
    summarize_state_root,
    write_candidates,
)
from app.loop.worker import run_candidate


class TestBuildBaselineCandidates:
    def test_n_candidates_includes_parent(self):
        payload = build_baseline_candidates(n=5, seed=1)
        assert len(payload["candidates"]) == 5
        assert payload["candidates"][0]["candidate_id"].endswith("000")
        # Parent is unmutated TUNING fields we care about
        assert payload["candidates"][0]["tuning"]["a_grade_min"] == TUNING.a_grade_min

    def test_write_candidates(self, tmp_path):
        payload = build_baseline_candidates(n=3)
        path = write_candidates(payload, tmp_path / "c.json")
        loaded = json.loads(path.read_text())
        assert len(loaded["candidates"]) == 3


class TestWorkerDryRun:
    def test_dry_run_writes_summary(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOOP_WORKER_DRY_RUN", "1")
        run_dir = tmp_path / "run1"
        r = run_candidate(
            candidate_id="c1",
            tuning=TUNING,
            symbol_set="BTCUSD",
            quarter=None,
            run_dir=run_dir,
        )
        assert r.decision == "accepted"
        assert r.fitness is not None
        assert (run_dir / "summary.json").exists()
        assert (run_dir / "tuning.yaml").exists()
        assert "dry_run" in (run_dir / "backtest.log").read_text()


class TestRunBaselineSmoke:
    def test_dry_run_generation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOOP_WORKER_DRY_RUN", "1")
        root = tmp_path / "phase0"
        summary = run_baseline(n=4, state_root=root, workers=2, seed=0)
        assert summary["history_records"] == 4
        assert summary["state_md_exists"]
        assert summary["pareto_size"] >= 1
        assert (root / "HISTORY.jsonl").exists()
        assert (root / "PARETO.json").exists()
        assert (root / "STATE.md").exists()

        # summarize helper matches
        s2 = summarize_state_root(root)
        assert s2["history_records"] == 4
