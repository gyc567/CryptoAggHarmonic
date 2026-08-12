"""Tests for FT Strategy repository (D-FT-08/19/20 + helper conventions).

Uses in-memory SQLite. Verifies:
- D-FT-08: refine() atomically bumps current_version via SQL expression
- D-FT-19: record_experiment rejects empty/short reasoning
- D-FT-20: publish_report locks final state; rejects TODO placeholders;
  rejects double-publish
- D-FT-21: research_md stored as opaque text (length check is at API layer)
- Event log: stamping + stagnation counter math
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.ft_strategy._schema_sqlite import SQLITE_DDL, apply_sqlite_schema
from app.ft_strategy.supabase_repo import (
    FtStrategyError,
    FtStrategyRepo,
    ReasoningEmpty,
    ReportFinalLocked,
    ReportInvalidFinal,
    StrategyNotFound,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    apply_sqlite_schema(c)
    yield c
    c.close()


@pytest.fixture
def repo(conn):
    return FtStrategyRepo(conn)


def _strategy(repo: FtStrategyRepo, user_id="u1", name="RSI v2") -> str:
    s = repo.create_strategy(
        user_id=user_id,
        name=name,
        research_md=(
            "## Decision\nx\n## Question\ny\n## Motivation\nz\n"
            "## Universe\nBTC/USDT\n## Constraints\nleverage=1\n"
            "## Failure modes\ndd\n## Open Qs\nq\n" + ("x" * 200)
        ),
        idea_payload={"kind": "template", "params": {"period": 14}},
    )
    return s.id


# ---------------------------------------------------------------------------
# Schema smoke
# ---------------------------------------------------------------------------


class TestSchema:
    def test_ddl_count_matches_seven_tables(self):
        # We declare 7 main tables; helper index DDLs exist for each
        create_count = sum(
            1 for s in SQLITE_DDL if s.lstrip().upper().startswith("CREATE TABLE")
        )
        assert create_count == 7

    def test_schema_idempotent(self, conn):
        # Calling apply twice is safe
        apply_sqlite_schema(conn)
        apply_sqlite_schema(conn)
        cur = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'ft_%'")
        rows = cur.fetchone()[0]
        # 7 main tables
        assert rows == 7


# ---------------------------------------------------------------------------
# strategies
# ---------------------------------------------------------------------------


class TestCreateStrategy:
    def test_creates_with_draft_status(self, repo):
        sid = _strategy(repo)
        s = repo.get_strategy(sid)
        assert s.status == "draft"
        assert s.current_version == 1
        assert s.user_id == "u1"
        assert s.idea_payload == {"kind": "template", "params": {"period": 14}}
        assert s.stagnation_count == 0
        assert s.last_event == "create"

    def test_research_md_stored_opaquely(self, repo):
        sid = _strategy(repo)
        s = repo.get_strategy(sid)
        assert "Decision" in (s.research_md or "")
        assert len(s.research_md) >= 200  # D-FT-21 length floor

    def test_get_strategy_raises_on_missing(self, repo):
        with pytest.raises(StrategyNotFound):
            repo.get_strategy("nonexistent-uuid")

    def test_create_assigns_unique_ids(self, repo):
        ids = {_strategy(repo, name=f"S{n}") for n in range(5)}
        assert len(ids) == 5


class TestUpdateStatus:
    def test_status_changes(self, repo):
        sid = _strategy(repo)
        repo.update_status(sid, "code_generated")
        s = repo.get_strategy(sid)
        assert s.status == "code_generated"


class TestUpdateLatestResult:
    def test_latest_result_round_trips_json(self, repo):
        sid = _strategy(repo)
        repo.update_latest_result(sid, {"sharpe": 1.5, "max_dd": 0.08})
        s = repo.get_strategy(sid)
        assert s.latest_result == {"sharpe": 1.5, "max_dd": 0.08}


class TestRefine:
    def test_bumps_version_atomically(self, repo):
        sid = _strategy(repo)
        s = repo.refine(sid)
        assert s.current_version == 2
        s2 = repo.refine(sid)
        assert s2.current_version == 3

    def test_refine_sets_status_refining(self, repo):
        sid = _strategy(repo)
        s = repo.refine(sid)
        assert s.status == "refining"

    def test_refine_missing_raises(self, repo):
        with pytest.raises(StrategyNotFound):
            repo.refine("nonexistent-uuid")


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


class TestRuns:
    def test_create_run_queued(self, repo):
        sid = _strategy(repo)
        run = repo.create_run(strategy_id=sid, version=1, stage="backtest")
        assert run.status == "queued"
        assert run.progress_pct == 0
        assert run.stage == "backtest"
        assert run.source == "ft_strategy_ui"

    def test_get_run_returns_created(self, repo):
        sid = _strategy(repo)
        run = repo.create_run(strategy_id=sid, version=1, stage="hyperopt")
        again = repo.get_run(run.id)
        assert again.id == run.id


# ---------------------------------------------------------------------------
# experiments (D-FT-19)
# ---------------------------------------------------------------------------


class TestExperiments:
    def test_record_experiment_ok(self, repo):
        sid = _strategy(repo)
        e = repo.record_experiment(
            strategy_id=sid,
            version_from=1,
            verdict="keep",
            reasoning="Sharpe improved and DD within bounds",
            metrics_delta={"sharpe_from": 1.0, "sharpe_to": 1.5},
        )
        assert e.verdict == "keep"
        assert e.version_to == 2  # auto-bumped

    def test_record_experiment_rejects_empty_reasoning(self, repo):
        sid = _strategy(repo)
        with pytest.raises(ReasoningEmpty):
            repo.record_experiment(
                strategy_id=sid, version_from=1, verdict="keep", reasoning=""
            )

    def test_record_experiment_rejects_short_reasoning(self, repo):
        sid = _strategy(repo)
        # REASONING_MIN_LENGTH = 10; "too short" is 9
        with pytest.raises(ReasoningEmpty):
            repo.record_experiment(
                strategy_id=sid, version_from=1, verdict="keep", reasoning="too short"
            )

    def test_record_experiment_rejects_whitespace_only(self, repo):
        sid = _strategy(repo)
        with pytest.raises(ReasoningEmpty):
            repo.record_experiment(
                strategy_id=sid, version_from=1, verdict="keep", reasoning="          "
            )

    def test_record_experiment_rejects_invalid_verdict(self, repo):
        sid = _strategy(repo)
        with pytest.raises(FtStrategyError):
            repo.record_experiment(
                strategy_id=sid, version_from=1, verdict="yolo",
                reasoning="this is long enough to pass the length check",
            )

    def test_record_experiment_with_decided_by(self, repo):
        sid = _strategy(repo)
        e = repo.record_experiment(
            strategy_id=sid, version_from=1, verdict="crash",
            reasoning="DD > 2x baseline, killing this strategy",
            decided_by="u1",
        )
        assert e.decided_by == "u1"

    def test_list_open_crashes(self, repo):
        sid = _strategy(repo)
        repo.record_experiment(
            strategy_id=sid, version_from=1, verdict="crash",
            reasoning="Crash due to oracle gaming ROI clipping",
        )
        repo.record_experiment(
            strategy_id=sid, version_from=2, verdict="crash",
            reasoning="Second crash; drawdown exceeded budget catastrophically",
            decided_by="u1",  # closed
        )
        # 1 open (decided_by=None), 1 closed
        assert repo.list_open_crashes(sid) == 1


# ---------------------------------------------------------------------------
# reports (D-FT-20)
# ---------------------------------------------------------------------------


class TestReports:
    def test_create_report_starts_draft(self, repo):
        sid = _strategy(repo)
        r = repo.create_report(
            strategy_id=sid, version=1,
            report_json={"summary": "test"},
        )
        assert r.authoring_state == "draft"
        assert r.published_at is None

    def test_publish_report_marks_final(self, repo):
        sid = _strategy(repo)
        r = repo.create_report(
            strategy_id=sid, version=1,
            report_json={"summary": "test"},
        )
        final = repo.publish_report(r.id, "Sharpe 1.5 holds across all 4 regimes tested")
        assert final.authoring_state == "final"
        assert final.published_at is not None
        assert final.reserved_finding == "Sharpe 1.5 holds across all 4 regimes tested"

    def test_publish_report_rejects_todo_placeholder(self, repo):
        sid = _strategy(repo)
        r = repo.create_report(
            strategy_id=sid, version=1, report_json={}
        )
        with pytest.raises(ReportInvalidFinal):
            repo.publish_report(r.id, "TODO: replace with real conclusion")

    def test_publish_report_rejects_empty_finding(self, repo):
        sid = _strategy(repo)
        r = repo.create_report(
            strategy_id=sid, version=1, report_json={}
        )
        with pytest.raises(ReportInvalidFinal):
            repo.publish_report(r.id, "")

    def test_publish_report_rejects_already_final(self, repo):
        sid = _strategy(repo)
        r = repo.create_report(
            strategy_id=sid, version=1, report_json={}
        )
        repo.publish_report(r.id, "Real finding text that satisfies length requirement")
        with pytest.raises(ReportFinalLocked):
            repo.publish_report(r.id, "Trying to publish again")

    def test_publish_report_accepts_short_non_todo_finding(self, repo):
        """Length checks are API-layer (worker); SQL CHECK only enforces NOT NULL + non-TODO."""
        sid = _strategy(repo)
        r = repo.create_report(strategy_id=sid, version=1, report_json={})
        # short but non-TODO is allowed at the repo; API worker enforces >= 10
        final = repo.publish_report(r.id, "ok")
        assert final.authoring_state == "final"

    def test_has_final_report(self, repo):
        sid = _strategy(repo)
        # No final yet
        assert not repo.has_final_report(sid)
        r = repo.create_report(strategy_id=sid, version=1, report_json={})
        # Draft only
        assert not repo.has_final_report(sid)
        repo.publish_report(r.id, "Final research conclusion: Sharpe 1.5 across all regimes")
        assert repo.has_final_report(sid)

    def test_get_report_raises_on_missing(self, repo):
        with pytest.raises(FtStrategyError):
            repo.get_report("nonexistent-uuid")


# ---------------------------------------------------------------------------
# events (D-FT-18)
# ---------------------------------------------------------------------------


class TestEvents:
    def test_record_event_returns_id(self, repo):
        sid = _strategy(repo)
        eid = repo.record_event(strategy_id=sid, event="stable", sharpe=1.5)
        assert isinstance(eid, int)
        assert eid > 0

    def test_record_invalid_event_rejected(self, repo):
        sid = _strategy(repo)
        with pytest.raises(FtStrategyError):
            repo.record_event(strategy_id=sid, event="hocus_pocus")

    def test_stable_event_increments_stagnation(self, repo):
        sid = _strategy(repo)
        s0 = repo.get_strategy(sid)
        assert s0.stagnation_count == 0
        # Note: ft_strategy_events must include this strategy_id
        # record_event bumps stagnation_count when event='stable'
        repo.record_event(strategy_id=sid, event="stable")
        s1 = repo.get_strategy(sid)
        assert s1.stagnation_count == 1
        repo.record_event(strategy_id=sid, event="stable")
        s2 = repo.get_strategy(sid)
        assert s2.stagnation_count == 2

    def test_evolve_event_resets_stagnation(self, repo):
        sid = _strategy(repo)
        for _ in range(3):
            repo.record_event(strategy_id=sid, event="stable")
        s_before = repo.get_strategy(sid)
        assert s_before.stagnation_count == 3
        repo.record_event(strategy_id=sid, event="evolve")
        s_after = repo.get_strategy(sid)
        assert s_after.stagnation_count == 0

    def test_recent_stable_count(self, repo):
        sid = _strategy(repo)
        # 3 stables, then 1 evolve, then 2 stables
        for _ in range(3):
            repo.record_event(strategy_id=sid, event="stable")
        repo.record_event(strategy_id=sid, event="evolve")
        for _ in range(2):
            repo.record_event(strategy_id=sid, event="stable")
        assert repo.recent_stable_count(sid) == 2  # only the last run

    def test_reset_stagnation(self, repo):
        sid = _strategy(repo)
        for _ in range(3):
            repo.record_event(strategy_id=sid, event="stable")
        repo.reset_stagnation(sid)
        s = repo.get_strategy(sid)
        assert s.stagnation_count == 0
        # recent_stable_count depends on event log, not stagnation_count
        assert repo.recent_stable_count(sid) == 3  # events persist

    def test_cascade_delete_removes_events(self, repo):
        sid = _strategy(repo)
        repo.record_event(strategy_id=sid, event="stable")
        repo.record_event(strategy_id=sid, event="stable")
        # FK ON DELETE CASCADE: removes events
        repo.conn.execute("DELETE FROM ft_strategies WHERE id = ?", (sid,))
        repo.conn.commit()
        cur = repo.conn.execute(
            "SELECT COUNT(*) FROM ft_strategy_events WHERE strategy_id = ?", (sid,)
        )
        assert cur.fetchone()[0] == 0


# ---------------------------------------------------------------------------
# JSON serialization integrity
# ---------------------------------------------------------------------------




class TestGetRunErrors:
    def test_missing_run_raises(self, repo):
        with pytest.raises(FtStrategyError):
            repo.get_run("nonexistent-uuid")

    def test_publish_missing_report_raises(self, repo):
        with pytest.raises(FtStrategyError):
            repo.publish_report("nonexistent-uuid", "valid finding text")

class TestJsonSerialization:
    def test_complex_idea_payload_round_trips(self, repo):
        payload = {
            "type": "natural_language",
            "text": "Buy when RSI < 30",
            "indicators": ["RSI", "EMA"],
            "nested": {"k": [1, 2, 3]},
        }
        sid = _strategy(repo)
        # Replace the default payload
        repo.conn.execute(
            "UPDATE ft_strategies SET idea_payload = ? WHERE id = ?",
            (json.dumps(payload), sid),
        )
        repo.conn.commit()
        s = repo.get_strategy(sid)
        assert s.idea_payload == payload
