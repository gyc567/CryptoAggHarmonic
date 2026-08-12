"""Tests for D-FT-18 dual-write event log.

Verifies:
- Both DB INSERT and .tsv append happen atomically (any failure rolls back)
- .tsv file structure matches Auto-Quant V1 ``results.tsv`` schema exactly
- Header is written on first append
- Crash-safe atomic write (tempfile + os.replace)
- read_tsv_events round-trips the rows
- Stagnation counter math triggers correctly
"""

from __future__ import annotations

import sqlite3

import pytest

from app.ft_strategy._schema_sqlite import apply_sqlite_schema
from app.ft_strategy.supabase_repo import FtStrategyRepo
from app.services.freqtrade.event_log import (
    ALLOWED_EVENTS,
    HEADER,
    EventLogError,
    record_event_dual,
    read_tsv_events,
    _format_row,
    _tsv_path,
)
from app.loop.tuning_promotion_v3 import STAGNATION_ROUNDS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tsv_root(tmp_path):
    p = tmp_path / "tsv_root"
    p.mkdir()
    return p


@pytest.fixture
def repo():
    c = sqlite3.connect(":memory:")
    apply_sqlite_schema(c)
    yield FtStrategyRepo(c)
    c.close()


@pytest.fixture
def strategy_id(repo):
    s = repo.create_strategy(
        user_id="u1",
        name="RSI v2",
        research_md=(
            "## Decision\nx\n## Question\ny\n## Motivation\nz\n"
            "## Universe\nBTC/USDT\n## Constraints\nleverage=1\n"
            "## Failure modes\ndd\n## Open Qs\nq\n" + ("x" * 200)
        ),
        idea_payload={"kind": "template"},
    )
    return s.id


# ---------------------------------------------------------------------------
# Format helper
# ---------------------------------------------------------------------------


class TestFormatRow:
    def test_basic_row(self):
        from app.services.freqtrade.event_log import EventLogEntry
        row = _format_row(EventLogEntry(
            event="stable",
            strategy_name="RSI v2",
            sharpe=1.5,
            max_dd=0.08,
            note="Sharpe improved",
        ))
        parts = row.split("\t")
        assert len(parts) == 6
        assert parts[1] == "stable"
        assert parts[2] == "RSI v2"
        assert parts[3] == "1.5"
        assert parts[4] == "0.08"
        assert "Sharpe improved" in parts[5]

    def test_empty_optional_fields(self):
        from app.services.freqtrade.event_log import EventLogEntry
        row = _format_row(EventLogEntry(event="create", strategy_name="S"))
        parts = row.split("\t")
        # commit, event, name, sharpe='', max_dd='', note=''
        assert parts[3] == ""
        assert parts[4] == ""

    def test_tabs_stripped_from_content(self):
        from app.services.freqtrade.event_log import EventLogEntry
        row = _format_row(EventLogEntry(
            event="stable",
            strategy_name="RSI\tv2",  # tab in name
            note="line1\nline2",  # newline in note
        ))
        # Must remain 6 tab-separated fields (newlines embedded in note
        # are stripped to spaces — _clean() enforces single-line rows)
        parts = row.split("\t")
        assert len(parts) == 6
        assert parts[2] == "RSI v2"   # tab stripped, joined with space
        assert "line1 line2" in parts[5]  # newline collapsed to space
        assert "\t" not in parts[2]


# ---------------------------------------------------------------------------
# Dual write
# ---------------------------------------------------------------------------


class TestDualWrite:
    def test_event_writes_to_both_db_and_tsv(self, repo, strategy_id, tsv_root):
        event_id = record_event_dual(
            repo,
            strategy_id=strategy_id,
            event="stable",
            strategy_name="RSI v2",
            sharpe=1.5,
            max_dd=0.08,
            note="Test event",
            tsv_root=tsv_root,
        )
        assert isinstance(event_id, int)

        # DB has the row
        cur = repo.conn.execute(
            "SELECT COUNT(*) FROM ft_strategy_events WHERE strategy_id = ?",
            (strategy_id,),
        )
        assert cur.fetchone()[0] == 1

        # .tsv has the row
        tsv_file = _tsv_path(tsv_root, strategy_id)
        assert tsv_file.exists()
        content = tsv_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 2  # header + 1 row
        assert lines[0] == HEADER

    def test_header_matches_autov1_schema(self, repo, strategy_id, tsv_root):
        record_event_dual(
            repo,
            strategy_id=strategy_id,
            event="create",
            strategy_name="S",
            tsv_root=tsv_root,
        )
        tsv_file = _tsv_path(tsv_root, strategy_id)
        first_line = tsv_file.read_text().split("\n")[0]
        # Auto-Quant V1 schema: commit | event | strategy_name | sharpe | max_dd | note
        assert first_line == "commit\tevent\tstrategy_name\tsharpe\tmax_dd\tnote"

    def test_multiple_events_append_in_order(self, repo, strategy_id, tsv_root):
        events = ["create", "evolve", "stable", "stable"]
        for ev in events:
            record_event_dual(
                repo,
                strategy_id=strategy_id,
                event=ev,
                strategy_name="S",
                tsv_root=tsv_root,
            )
        rows = read_tsv_events(tsv_root, strategy_id)
        assert [r["event"] for r in rows] == events

    def test_stable_event_increments_stagnation(self, repo, strategy_id, tsv_root):
        # Just-created strategy has stagnation_count=0
        s = repo.get_strategy(strategy_id)
        # create_strategy sets last_event='create' but stagnation_count=0
        assert s.stagnation_count == 0

        record_event_dual(
            repo, strategy_id=strategy_id, event="stable",
            strategy_name="S", tsv_root=tsv_root,
        )
        s = repo.get_strategy(strategy_id)
        assert s.stagnation_count == 1

    def test_evolve_event_resets_stagnation(self, repo, strategy_id, tsv_root):
        # Force stagnation up to threshold
        for _ in range(STAGNATION_ROUNDS):
            record_event_dual(
                repo, strategy_id=strategy_id, event="stable",
                strategy_name="S", tsv_root=tsv_root,
            )
        s = repo.get_strategy(strategy_id)
        assert s.stagnation_count == STAGNATION_ROUNDS

        # Now evolve -> reset
        record_event_dual(
            repo, strategy_id=strategy_id, event="evolve",
            strategy_name="S", tsv_root=tsv_root,
        )
        s = repo.get_strategy(strategy_id)
        assert s.stagnation_count == 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_unknown_event_rejected(self, repo, strategy_id, tsv_root):
        with pytest.raises(EventLogError):
            record_event_dual(
                repo,
                strategy_id=strategy_id,
                event="hocus_pocus",
                strategy_name="S",
                tsv_root=tsv_root,
            )

    def test_empty_strategy_name_rejected(self, repo, strategy_id, tsv_root):
        with pytest.raises(EventLogError):
            record_event_dual(
                repo,
                strategy_id=strategy_id,
                event="create",
                strategy_name="",
                tsv_root=tsv_root,
            )

    def test_whitespace_strategy_name_rejected(self, repo, strategy_id, tsv_root):
        with pytest.raises(EventLogError):
            record_event_dual(
                repo,
                strategy_id=strategy_id,
                event="create",
                strategy_name="   ",
                tsv_root=tsv_root,
            )


# ---------------------------------------------------------------------------
# Allowed events set
# ---------------------------------------------------------------------------


class TestAllowedEvents:
    def test_set_includes_plan_events(self):
        # Plan §1.5: create, evolve, stable, fork, kill (+ shadow_start, shadow_end)
        assert "create" in ALLOWED_EVENTS
        assert "evolve" in ALLOWED_EVENTS
        assert "stable" in ALLOWED_EVENTS
        assert "fork" in ALLOWED_EVENTS
        assert "kill" in ALLOWED_EVENTS
        assert "shadow_start" in ALLOWED_EVENTS
        assert "shadow_end" in ALLOWED_EVENTS


# ---------------------------------------------------------------------------
# read_tsv_events
# ---------------------------------------------------------------------------


class TestReadTsvEvents:
    def test_empty_when_no_file(self, tsv_root):
        assert read_tsv_events(tsv_root, "nonexistent-uuid") == []

    def test_round_trip(self, repo, strategy_id, tsv_root):
        for ev in ["create", "stable", "stable"]:
            record_event_dual(
                repo, strategy_id=strategy_id, event=ev,
                strategy_name="My Strat", sharpe=1.5, tsv_root=tsv_root,
            )
        rows = read_tsv_events(tsv_root, strategy_id)
        assert len(rows) == 3
        assert rows[0]["event"] == "create"
        assert rows[0]["strategy_name"] == "My Strat"
        assert rows[2]["event"] == "stable"

    def test_empty_file_handled(self, tsv_root):
        # Hand-craft an empty file to confirm graceful handling
        path = _tsv_path(tsv_root, "x-uuid")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        assert read_tsv_events(tsv_root, "x-uuid") == []

    def test_header_only(self, tsv_root):
        path = _tsv_path(tsv_root, "x-uuid")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(HEADER + "\n")
        assert read_tsv_events(tsv_root, "x-uuid") == []


# ---------------------------------------------------------------------------
# Atomic write safety (D-FT-18)
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_concurrent_appends_safe(self, repo, strategy_id, tsv_root):
        # Sequential writes from same process are always safe (sqlite + tempfile).
        for i in range(5):
            record_event_dual(
                repo,
                strategy_id=strategy_id,
                event="stable" if i % 2 == 0 else "evolve",
                strategy_name="S",
                sharpe=1.0 + i * 0.1,
                note=f"event {i}",
                tsv_root=tsv_root,
            )
        rows = read_tsv_events(tsv_root, strategy_id)
        assert len(rows) == 5
        # No orphaned tempfiles
        tempfiles = list(tsv_root.glob(f"{strategy_id}.tsv.*"))
        assert tempfiles == [], f"orphan tempfiles: {tempfiles}"

    def test_no_stray_tempfiles_after_normal_run(self, repo, strategy_id, tsv_root):
        # Run several events and verify no .tsv.* leftover
        for ev in ["create", "evolve", "stable", "stable", "stable"]:
            record_event_dual(
                repo, strategy_id=strategy_id, event=ev,
                strategy_name="S", tsv_root=tsv_root,
            )
        leftovers = list(tsv_root.glob("*.tmp*")) + list(tsv_root.glob(f"{strategy_id}.tsv.*"))
        assert leftovers == []


# ---------------------------------------------------------------------------
# Default tsv root
# ---------------------------------------------------------------------------


class TestDefaultTsvRoot:
    def test_default_root_is_scratch(self, monkeypatch, tmp_path):
        # Override the module-level default to a tmp dir for this test
        import app.services.freqtrade.event_log as evlog
        monkeypatch.setattr(evlog, "DEFAULT_TSV_ROOT", tmp_path / "scratch")

        # New in-memory repo + strategy
        c = sqlite3.connect(":memory:")
        apply_sqlite_schema(c)
        repo = FtStrategyRepo(c)
        s = repo.create_strategy(
            user_id="u1", name="S",
            research_md="## Decision\nx\n## Question\ny\n## Motivation\nz\n## Universe\nu\n## Constraints\nc\n## Failure modes\nf\n## Open Qs\nq\n" + ("x" * 200),
            idea_payload={},
        )
        record_event_dual(
            repo,
            strategy_id=s.id,
            event="create",
            strategy_name="S",
        )
        target = tmp_path / "scratch" / f"{s.id}.tsv"
        assert target.exists()
        c.close()


# ---------------------------------------------------------------------------
# D-FT-18 honesty: rollback semantics
# ---------------------------------------------------------------------------


class TestRollbackSemantics:
    def test_strategy_not_found_does_not_write_tsv(self, repo, tsv_root):
        # Trying to record an event for a missing strategy must not
        # leave a stray .tsv file behind.
        with pytest.raises(EventLogError):
            record_event_dual(
                repo,
                strategy_id="nonexistent-uuid",
                event="create",
                strategy_name="S",
                tsv_root=tsv_root,
            )
        # No .tsv file should exist
        stray = list(tsv_root.glob("nonexistent-uuid.tsv"))
        assert stray == []


class TestEdgeCases:
    def test_savepoint_rollback_when_outer_raises(self):
        # Simulate .tsv failure mid-transaction: row should NOT land in DB.
        import sqlite3
        from app.services.freqtrade.event_log import _event_log_transaction

        c = sqlite3.connect(":memory:")
        try:
            repo = FtStrategyRepo(c)
            try:
                with _event_log_transaction(repo):
                    repo.conn.execute(
                        "INSERT INTO ft_strategies (id, name, idea_payload) VALUES (?, ?, ?)",
                        ("rollback-test", "S", "{}"),
                    )
                    raise RuntimeError("simulated .tsv failure after DB write")
            except RuntimeError:
                pass
            cur = repo.conn.execute(
                "SELECT COUNT(*) FROM ft_strategies WHERE id = ?", ("rollback-test",)
            )
            assert cur.fetchone()[0] == 0, "savepoint should have rolled back"
        finally:
            c.close()


class TestMoreEdgeCases:
    def test_git_commit_unavailable(self, monkeypatch):
        # Force _git_commit_short() to fall through its except branch.
        import app.services.freqtrade.event_log as evlog
        # Replace subprocess.check_output inside the module
        def boom(*a, **kw):
            raise FileNotFoundError("no git")
        monkeypatch.setattr(evlog.subprocess, "check_output", boom)
        assert evlog._git_commit_short() == "no-git"

    def test_git_commit_returns_empty_string(self, monkeypatch):
        import app.services.freqtrade.event_log as evlog
        import subprocess
        class FakeOut:
            def decode(self):
                return ""
        monkeypatch.setattr(evlog.subprocess, "check_output", lambda *a, **kw: FakeOut())
        # empty stdout -> fallback to "no-git"
        assert evlog._git_commit_short() == "no-git"

    def test_append_file_with_final_no_trailing_newline(self, tsv_root):
        # Force the missing-trailing-newline branch
        from app.services.freqtrade.event_log import _append_crash_safe
        path = _tsv_path(tsv_root, "edge-no-newline")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("HEADER_NO_NEWLINE")  # no \n
        _append_crash_safe(path, "row1")
        # Newline gets inserted by _append_crash_safe
        content = path.read_text()
        assert content.endswith("\n")
        assert "HEADER_NO_NEWLINE" in content
        assert "row1" in content

    def test_append_exception_triggers_cleanup(self, tsv_root, monkeypatch):
        from app.services.freqtrade.event_log import _append_crash_safe
        # Inject os.replace failure to hit the cleanup branch
        from app.services.freqtrade import event_log as evmod
        def fail_replace(*a, **kw):
            raise OSError("disk full")
        monkeypatch.setattr(evmod.os, "replace", fail_replace)
        path = _tsv_path(tsv_root, "boom")
        path.parent.mkdir(parents=True, exist_ok=True)
        with pytest.raises(OSError):
            _append_crash_safe(path, "row1")

    def test_savepoint_release_without_failure(self, repo):
        # Covers the "else: RELEASE" branch
        import sqlite3
        from app.services.freqtrade.event_log import _event_log_transaction

        c = repo.conn  # reuse in-memory connection
        with _event_log_transaction(repo):
            pass  # no exceptions => RELEASE branch fires

    def test_record_event_dual_strategy_missing(self, repo, tsv_root):
        # Direct call with nonexistent strategy_id should raise EventLogError
        from app.services.freqtrade.event_log import EventLogError
        with pytest.raises(EventLogError):
            record_event_dual(
                repo, strategy_id="no-such-strategy", event="create",
                strategy_name="S", tsv_root=tsv_root,
            )

    def test_record_event_dual_db_id_unexpected_none(self, repo, strategy_id, tsv_root, monkeypatch):
        # Force db_event_id to remain None by mocking record_event to return None
        from app.services.freqtrade import event_log as evlog
        from contextlib import contextmanager

        @contextmanager
        def fake_transaction(r):
            yield None

        monkeypatch.setattr(evlog, "_event_log_transaction", fake_transaction)
        original = repo.record_event
        monkeypatch.setattr(repo, "record_event",
                            lambda **kw: None)

        with pytest.raises(evlog.EventLogError):
            evlog.record_event_dual(
                repo, strategy_id=strategy_id, event="create",
                strategy_name="S", tsv_root=tsv_root,
            )

    def test_read_tsv_events_short_row_padding(self, tsv_root):
        # Hand-craft a row with fewer fields than header to cover the `while` pad branch
        path = _tsv_path(tsv_root, "short-row")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(HEADER + "\nshort_row_with_only_2_fields\n")
        rows = read_tsv_events(tsv_root, "short-row")
        assert len(rows) == 1
        assert rows[0]["commit"] == "short_row_with_only_2_fields"
        # missing cols padded as empty
        assert rows[0]["event"] == ""  # padded


class TestSavepointFailurePaths:
    def test_savepoint_creation_fails_yields_anyway(self):
        # Construct a repo whose conn.cursor() raises on SAVEPOINT
        # but otherwise still completes the with-block successfully.
        from app.services.freqtrade import event_log as evlog

        class FakeCursor:
            def __init__(self):
                self.calls = 0
            def execute(self, sql, *args):
                self.calls += 1
                if sql.startswith("SAVEPOINT"):
                    raise RuntimeError("savepoint unsupported")
                # Savepoint release/rollback: also fail (must be swallowed)
                if sql.startswith("RELEASE") or sql.startswith("ROLLBACK"):
                    raise RuntimeError("also fail")

        class FakeRepo:
            def __init__(self):
                self.cursor_obj = FakeCursor()
            @property
            def conn(self):
                class C:
                    def cursor(self_inner):
                        return self.cursor_obj
                return C()

        with evlog._event_log_transaction(FakeRepo()):
            pass  # if no exception escapes, all branches were swallowed

    def test_record_event_dual_tsv_append_failure(self, repo, strategy_id, tsv_root, monkeypatch):
        # Force _append_crash_safe to raise -> wraps as EventLogError
        from app.services.freqtrade import event_log as evlog
        def fail(*a, **kw):
            raise IOError("disk full")
        monkeypatch.setattr(evlog, "_append_crash_safe", fail)
        with pytest.raises(evlog.EventLogError) as exc:
            record_event_dual(
                repo, strategy_id=strategy_id, event="create",
                strategy_name="S", tsv_root=tsv_root,
            )
        assert ".tsv write failed" in str(exc.value)


class TestTempfileCleanup:
    def test_osreplace_failure_triggers_unlink_failure_swallow(self, tsv_root, monkeypatch):
        # os.replace fails; os.unlink also fails (e.g. temp already removed)
        # The OSError handler must swallow silently.
        from app.services.freqtrade import event_log as evlog
        from app.services.freqtrade.event_log import _append_crash_safe

        def fail_replace(*a, **kw):
            raise OSError("disk full")
        def fail_unlink(*a, **kw):
            raise OSError("file already gone")
        monkeypatch.setattr(evlog.os, "replace", fail_replace)
        monkeypatch.setattr(evlog.os, "unlink", fail_unlink)
        path = _tsv_path(tsv_root, "cleanup-fail")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Must propagate the replace error, but swallow the unlink error
        with pytest.raises(OSError, match="disk full"):
            _append_crash_safe(path, "row1")
