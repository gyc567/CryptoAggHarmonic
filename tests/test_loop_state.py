"""Tests for ``app.loop`` — durable state + Pareto maintenance + driver glue.

These tests cover the M2 scaffolding WITHOUT running the actual v3
backtest (that takes ~3 minutes and is integration-tested separately).
The driver and worker modules have their own subprocess boundary so we
mock the subprocess invocation.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from app.config.tuning import TUNING, from_dict, to_dict, TuningConstants
from app.loop import state
from app.loop.pareto import (
    ParetoPoint,
    ParetoSet,
    dominates,
    from_metrics,
    load as pareto_load,
    save as pareto_save,
    worst_regime_sharpe,
)


# --- state.py ----------------------------------------------------------------


class TestEnsureRoot:
    def test_creates_subdirectories(self, tmp_path):
        root = state.ensure_root(tmp_path)
        for sub in ("runs", "tuning_snapshots", "REJECTED", "archive"):
            assert (root / sub).is_dir()

    def test_idempotent(self, tmp_path):
        state.ensure_root(tmp_path)
        state.ensure_root(tmp_path)  # second call must not raise


class TestParamsSha:
    def test_same_instance_same_sha(self):
        assert state.params_sha(TUNING) == state.params_sha(TUNING)

    def test_perturbed_instance_different_sha(self):
        from dataclasses import replace
        t2 = replace(TUNING, a_grade_min=80)
        assert state.params_sha(t2) != state.params_sha(TUNING)


class TestHistoryAppend:
    def test_append_creates_file(self, tmp_path):
        state.append_history({"ts": 1, "gen": 1, "candidate_id": "x"},
                             root=tmp_path)
        path = tmp_path / "HISTORY.jsonl"
        assert path.exists()
        with open(path) as f:
            line = f.readline().strip()
        rec = json.loads(line)
        assert rec["candidate_id"] == "x"

    def test_concurrent_append(self, tmp_path):
        # fcntl.flock is per-process; use threads to ensure no corruption.
        import threading

        def worker(i):
            state.append_history({"ts": i, "gen": 1, "candidate_id": f"c{i}"},
                                 root=tmp_path)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with open(tmp_path / "HISTORY.jsonl") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        assert len(lines) == 20
        ids = {json.loads(ln)["candidate_id"] for ln in lines}
        assert len(ids) == 20

    def test_rotation(self, tmp_path):
        # Inject a tiny rotation threshold for the test.
        state.append_history(
            {"big": "x" * 100, "ts": 1}, root=tmp_path,
            rotate_bytes=200,
        )
        # Second call should rotate.
        state.append_history(
            {"big": "y" * 200, "ts": 2}, root=tmp_path,
            rotate_bytes=200,
        )
        rotated = list(tmp_path.glob("HISTORY-*.jsonl.gz"))
        assert len(rotated) == 1


class TestAtomicWriteJson:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "out.json"
        state.atomic_write_json(path, {"a": 1, "b": [1, 2, 3]})
        with open(path) as f:
            assert json.load(f) == {"a": 1, "b": [1, 2, 3]}

    def test_overwrite_existing(self, tmp_path):
        path = tmp_path / "out.json"
        state.atomic_write_json(path, {"old": True})
        state.atomic_write_json(path, {"new": True})
        with open(path) as f:
            assert json.load(f) == {"new": True}


class TestReplay:
    def test_replay_roundtrip(self, tmp_path):
        for i in range(3):
            state.append_history({"ts": i, "gen": 1, "id": f"c{i}"},
                                 root=tmp_path)
        recs = state.replay_from_history(tmp_path)
        assert [r["id"] for r in recs] == ["c0", "c1", "c2"]


class TestStateMd:
    def test_render_with_no_best(self):
        body = state.render_state_md()
        assert "Plateau count" in body
        assert "_(none yet)_" in body

    def test_render_with_best(self):
        body = state.render_state_md(
            best={"params_sha": "abc123", "gen": 2, "fitness": 1.5,
                  "sharpe": 0.4, "calmar": 1.0, "profit_factor": 2.0,
                  "trade_count": 30},
            pareto_size=3, plateau_count=1, next_queue_size=5,
            last_decision="accepted=2 rejected=1",
            notes=["cluster: C3"],
        )
        assert "abc123" in body
        assert "1.5" in body
        assert "C3" in body

    def test_write_replaces_atomically(self, tmp_path):
        state.write_state_md("# Hello\n", root=tmp_path)
        state.write_state_md("# World\n", root=tmp_path)
        content = (tmp_path / "STATE.md").read_text()
        assert content.startswith("# World\n")


# --- pareto.py ----------------------------------------------------------------


def _mkpoint(sha, sharpe=0.3, calmar=1.0, pf=2.0, wreg=0.0, tc=30, **kw):
    return ParetoPoint(
        params_sha=sha, gen=1, cluster="C3", run_dir=f"runs/{sha}",
        sharpe=sharpe, calmar=calmar, profit_factor=pf,
        worst_regime_sharpe=wreg, trade_count=tc, fitness=0.0,
        **kw,
    )


class TestDominates:
    def test_dominates_basic(self):
        a = _mkpoint("a", sharpe=0.5, calmar=2.0, pf=3.0)
        b = _mkpoint("b", sharpe=0.3, calmar=1.0, pf=2.0)
        assert dominates(a, b)
        assert not dominates(b, a)

    def test_no_dominance_when_each_better_one_obj(self):
        a = _mkpoint("a", sharpe=0.5, calmar=1.0, pf=3.0)
        b = _mkpoint("b", sharpe=0.3, calmar=2.0, pf=2.0)
        assert not dominates(a, b)
        assert not dominates(b, a)

    def test_dominance_with_none_metric(self):
        # None treated as worst-case so a point with a missing metric
        # never dominates a complete one.
        a = _mkpoint("a", sharpe=0.5, calmar=None, pf=2.0)
        b = _mkpoint("b", sharpe=0.3, calmar=1.0, pf=1.0)
        assert not dominates(a, b)


class TestParetoSet:
    def test_add_dominates_existing(self):
        ps = ParetoSet()
        assert ps.add(_mkpoint("a", sharpe=0.3)) is True
        # Better on every metric.
        assert ps.add(_mkpoint("b", sharpe=0.5, calmar=2.0, pf=3.0)) is True
        # ``a`` should have been pruned.
        assert len(ps) == 1
        assert ps.points[0].params_sha == "b"

    def test_add_rejected_when_dominated(self):
        ps = ParetoSet()
        ps.add(_mkpoint("a", sharpe=0.5, calmar=2.0, pf=3.0))
        assert ps.add(_mkpoint("b", sharpe=0.3, calmar=1.0, pf=1.0)) is False
        assert len(ps) == 1

    def test_dedupe_same_sha(self):
        ps = ParetoSet()
        ps.add(_mkpoint("a"))
        assert ps.add(_mkpoint("a")) is False
        assert len(ps) == 1

    def test_non_dominated_addition(self):
        ps = ParetoSet()
        ps.add(_mkpoint("a", sharpe=0.5, calmar=1.0, pf=3.0))
        # Better on calmar+pf, worse on sharpe — both stay.
        ps.add(_mkpoint("b", sharpe=0.3, calmar=2.0, pf=4.0))
        assert len(ps) == 2


class TestParetoIO:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "PARETO.json"
        ps = ParetoSet()
        # Two truly non-dominated points: each dominates one metric only.
        ps.add(_mkpoint("a", sharpe=0.5, calmar=1.0, pf=2.0))
        ps.add(_mkpoint("b", sharpe=0.3, calmar=2.0, pf=2.0))
        assert len(ps) == 2
        pareto_save(path, ps)
        loaded = pareto_load(path)
        assert {p.params_sha for p in loaded} == {"a", "b"}

    def test_load_missing_file(self, tmp_path):
        ps = pareto_load(tmp_path / "PARETO.json")
        assert len(ps) == 0


class TestWorstRegimeSharpe:
    def test_empty_regimes(self):
        assert worst_regime_sharpe({"by_regime": {}}) is None

    def test_one_regime_under_threshold(self):
        # n < 3 buckets are skipped (insufficient sample).
        m = {"by_regime": {"bull": {"n": 1, "sharpe": 5.0}}}
        assert worst_regime_sharpe(m) is None

    def test_picks_minimum(self):
        m = {"by_regime": {
            "bull": {"n": 10, "sharpe": 0.5},
            "bear": {"n": 8, "sharpe": -0.3},
            "range": {"n": 5, "sharpe": 0.2},
        }}
        assert worst_regime_sharpe(m) == pytest.approx(-0.3)


class TestFromMetrics:
    def test_full_metrics(self):
        m = {
            "trades_count": 35, "sharpe": 0.4, "calmar": 1.5,
            "profit_factor": 2.0,
            "by_regime": {"bull": {"n": 20, "sharpe": 0.6},
                          "range": {"n": 5, "sharpe": -0.1}},
        }
        p = from_metrics(
            metrics=m, params_sha="xyz", gen=2, cluster="C3",
            run_dir="runs/xyz", fitness=1.0,
        )
        assert p.params_sha == "xyz"
        assert p.sharpe == 0.4
        assert p.trade_count == 35
        assert p.worst_regime_sharpe == pytest.approx(-0.1)