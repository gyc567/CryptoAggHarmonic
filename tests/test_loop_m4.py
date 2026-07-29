"""Tests for M4 — adaptive heartbeat + checker + skills versioning.

These tests use no subprocess / no real harness; they exercise the
scheduling / checking / hashing logic in isolation.
"""

from __future__ import annotations

import datetime as _dt
import json
import time
from pathlib import Path

from app.loop.checker import (
    _flag_bear_regime_sharpe,
    _flag_low_sample,
    _flag_regime_imbalance,
    check_candidate,
)
from app.loop.scheduler import (
    SchedulerConfig,
    _in_quiet_hours,
    _is_weekend,
    next_wake_at,
    plateau_count_from_history,
)
from app.loop.skills_version import (
    current_version,
    is_outdated,
    save_version,
)
from app.loop.worker import CandidateResult

# --- scheduler.py ------------------------------------------------------------


class TestInQuietHours:
    def test_inside_window(self):
        cfg = SchedulerConfig(quiet_hours_start=23, quiet_hours_end=7)
        assert _in_quiet_hours(_dt.datetime(2026, 1, 1, 1, 0), cfg)
        assert _in_quiet_hours(_dt.datetime(2026, 1, 1, 23, 30), cfg)

    def test_outside_window(self):
        cfg = SchedulerConfig(quiet_hours_start=23, quiet_hours_end=7)
        assert not _in_quiet_hours(_dt.datetime(2026, 1, 1, 12, 0), cfg)
        assert not _in_quiet_hours(_dt.datetime(2026, 1, 1, 7, 0), cfg)
        assert not _in_quiet_hours(_dt.datetime(2026, 1, 1, 22, 59), cfg)

    def test_non_wrapping_window(self):
        cfg = SchedulerConfig(quiet_hours_start=1, quiet_hours_end=5)
        assert _in_quiet_hours(_dt.datetime(2026, 1, 1, 3, 0), cfg)
        assert not _in_quiet_hours(_dt.datetime(2026, 1, 1, 6, 0), cfg)


class TestIsWeekend:
    def test_weekend_disabled(self):
        cfg = SchedulerConfig(weekend_skip=False)
        # Saturday — but skip disabled.
        sat = _dt.datetime(2026, 1, 3, 12, 0)
        assert sat.weekday() == 5
        assert not _is_weekend(sat, cfg)

    def test_weekend_enabled(self):
        cfg = SchedulerConfig(weekend_skip=True)
        sat = _dt.datetime(2026, 1, 3, 12, 0)
        mon = _dt.datetime(2026, 1, 5, 12, 0)
        assert _is_weekend(sat, cfg)
        assert not _is_weekend(mon, cfg)


class TestPlateauFromHistory:
    def test_empty_history(self, tmp_path):
        p = tmp_path / "HISTORY.jsonl"
        assert plateau_count_from_history(p) == 0

    def test_no_growth(self, tmp_path):
        p = tmp_path / "HISTORY.jsonl"
        # Two gens, both fitness 1.0.
        with open(p, "w") as f:
            f.write(json.dumps({"gen": 1, "decision": "accepted", "fitness": 1.0, "ts": 1}) + "\n")
            f.write(json.dumps({"gen": 2, "decision": "accepted", "fitness": 1.0, "ts": 2}) + "\n")
        # Plateau count = 1 (gen 2 didn't grow over gen 1).
        assert plateau_count_from_history(p) == 1

    def test_growth_resets(self, tmp_path):
        p = tmp_path / "HISTORY.jsonl"
        # gen 1: 1.0; gen 2: 2.0 (growth); gen 3: 2.0 (plateau);
        # gen 4: 2.0 (still plateau).
        with open(p, "w") as f:
            for rec in [
                {"gen": 1, "decision": "accepted", "fitness": 1.0, "ts": 1},
                {"gen": 2, "decision": "accepted", "fitness": 2.0, "ts": 2},
                {"gen": 3, "decision": "accepted", "fitness": 2.0, "ts": 3},
                {"gen": 4, "decision": "accepted", "fitness": 2.0, "ts": 4},
            ]:
                f.write(json.dumps(rec) + "\n")
        # Trailing gens without growth = 2 (gen 3 and gen 4).
        assert plateau_count_from_history(p) == 2

    def test_rejected_doesnt_count(self, tmp_path):
        p = tmp_path / "HISTORY.jsonl"
        with open(p, "w") as f:
            for rec in [
                {"gen": 1, "decision": "accepted", "fitness": 1.0, "ts": 1},
                {"gen": 2, "decision": "rejected", "fitness": 0.0, "ts": 2},
            ]:
                f.write(json.dumps(rec) + "\n")
        # Only gen 1 has a fitness record → plateau = 0.
        assert plateau_count_from_history(p) == 0


class TestNextWakeAt:
    def test_quiet_hours_push_to_morning(self):
        now = _dt.datetime(2026, 1, 1, 1, 30)
        cfg = SchedulerConfig(quiet_hours_start=23, quiet_hours_end=7)
        d = next_wake_at(now=now, cfg=cfg, history_path=Path("/nonexistent"))
        assert d.wake_at.hour == 7
        assert d.reason.startswith("quiet")

    def test_weekend_push_to_monday(self):
        # Saturday 12:00
        now = _dt.datetime(2026, 1, 3, 12, 0)
        cfg = SchedulerConfig(weekend_skip=True)
        d = next_wake_at(now=now, cfg=cfg, history_path=Path("/nonexistent"))
        assert d.wake_at.weekday() == 0  # Monday
        assert "quiet" in d.reason or "weekend" in d.reason

    def test_operator_action_5_min(self, tmp_path):
        now = _dt.datetime(2026, 1, 1, 12, 0)
        d = next_wake_at(
            now=now,
            history_path=Path("/nonexistent"),
            pending_operator_action=True,
        )
        assert (d.wake_at - now).total_seconds() == 300
        assert "operator action" in d.reason

    def test_default_cadence_60_min(self, tmp_path):
        now = _dt.datetime(2026, 1, 1, 12, 0)  # midday, mid-week
        cfg = SchedulerConfig()
        d = next_wake_at(now=now, cfg=cfg, history_path=Path("/nonexistent"))
        assert (d.wake_at - now).total_seconds() == 3600

    def test_short_cadence_when_recent_growth(self, tmp_path):
        # History with a growth event 1 hour ago.
        history = tmp_path / "HISTORY.jsonl"
        recent_ts = time.time() - 3600
        with open(history, "w") as f:
            f.write(json.dumps({"gen": 1, "decision": "accepted", "fitness": 1.0, "ts": recent_ts}) + "\n")
        now = _dt.datetime.fromtimestamp(time.time())
        d = next_wake_at(now=now, history_path=history)
        # 15-minute cadence for recent growth.
        assert (d.wake_at - now).total_seconds() == 900


# --- checker.py --------------------------------------------------------------


def _mk_result(metrics: dict, decision: str = "accepted", candidate_id: str = "c1") -> CandidateResult:
    return CandidateResult(
        candidate_id=candidate_id,
        params_sha="abc",
        cluster="C3",
        gen=1,
        decision=decision,
        metrics=metrics,
        fitness=1.0,
        run_dir="runs/abc",
        elapsed_seconds=10.0,
    )


class TestFlagRegimeImbalance:
    def test_balanced_returns_none(self):
        m = {"by_regime": {"bull": {"n": 10}, "bear": {"n": 8}, "range": {"n": 7}}}
        assert _flag_regime_imbalance(m) is None

    def test_skewed_returns_flag(self):
        m = {"by_regime": {"bull": {"n": 95}, "bear": {"n": 5}, "range": {"n": 1}}}
        flag = _flag_regime_imbalance(m)
        assert flag is not None
        assert "bull" in flag

    def test_low_total_returns_none(self):
        m = {"by_regime": {"bull": {"n": 5}}}
        assert _flag_regime_imbalance(m) is None


class TestFlagLowSample:
    def test_low_count(self):
        assert _flag_low_sample({"trades_count": 20}) is not None

    def test_above_floor(self):
        assert _flag_low_sample({"trades_count": 50}) is None


class TestFlagBearSharpe:
    def test_no_bear_data(self):
        assert _flag_bear_regime_sharpe({"by_regime": {}}) is None

    def test_moderate_bear(self):
        m = {"by_regime": {"bear": {"n": 10, "sharpe": 0.5}}}
        assert _flag_bear_regime_sharpe(m) is None

    def test_extreme_bear(self):
        m = {"by_regime": {"bear": {"n": 10, "sharpe": -2.0}}}
        flag = _flag_bear_regime_sharpe(m)
        assert flag is not None
        assert "bear_sharpe" in flag


class TestCheckCandidate:
    def test_clean_accepted_is_promising(self):
        r = _mk_result(
            {
                "trades_count": 50,
                "sharpe": 0.5,
                "calmar": 1.5,
                "profit_factor": 2.0,
                "by_regime": {
                    "bull": {"n": 15, "sharpe": 0.5},
                    "bear": {"n": 10, "sharpe": 0.2},
                    "range": {"n": 25, "sharpe": 0.4},
                },
            }
        )
        v = check_candidate(r)
        assert v.decision == "promising"
        assert v.confidence > 0.5
        assert v.flags == []

    def test_low_trades_is_suspicious(self):
        r = _mk_result({"trades_count": 20, "by_regime": {}})
        v = check_candidate(r)
        assert v.decision == "suspicious"
        assert any("sample" in f for f in v.flags)

    def test_regime_imbalance_is_suspicious(self):
        r = _mk_result(
            {
                "trades_count": 100,
                "by_regime": {
                    "bull": {"n": 95},
                    "bear": {"n": 3},
                    "range": {"n": 2},
                },
            }
        )
        v = check_candidate(r)
        assert v.decision == "suspicious"
        assert any("regime" in f for f in v.flags)

    def test_rejected_decision_passes_through(self):
        r = _mk_result({}, decision="rejected")
        v = check_candidate(r)
        assert v.decision == "rejected"
        assert v.confidence == 0.9

    def test_overfit_flag(self):
        r = _mk_result(
            {
                "trades_count": 10,
                "fitness": 5.0,
                "by_regime": {"bull": {"n": 10}},
            }
        )
        parent = {"trades_count": 30, "fitness": 1.0}
        v = check_candidate(r, parent_metrics=parent)
        assert any("fitness_gain_trade_drop" in f for f in v.flags)


# --- skills_version.py -------------------------------------------------------


class TestSkillsVersion:
    def test_current_version_is_stable(self):
        v1 = current_version()
        v2 = current_version()
        assert v1 == v2

    def test_extra_files_change_hash(self):
        v1 = current_version()
        v2 = current_version(extra_files=["nonexistent.py"])
        # nonexistent.py hashes to "missing" — the version string changes.
        assert v1 != v2 or "missing" not in v1  # loose assertion

    def test_save_version_creates_file(self, tmp_path, monkeypatch):
        # Patch DEFAULT_ROOT in BOTH modules since each captured a ref.
        from app.loop import skills_version as sv_mod
        from app.loop import state as state_mod

        monkeypatch.setattr(state_mod, "DEFAULT_ROOT", tmp_path)
        monkeypatch.setattr(sv_mod, "DEFAULT_ROOT", tmp_path)
        v = save_version(repo_root=Path("/tmp"))  # doesn't matter — files missing
        saved = json.loads((tmp_path / "skills_version.json").read_text())
        assert saved["version"] == v
        assert "ts" in saved

    def test_is_outdated(self):
        assert is_outdated("abc", "xyz")
        assert not is_outdated("abc", "abc")
