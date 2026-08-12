"""Tests for D-FT-20 report final-state validator + DB CHECK parity."""

from __future__ import annotations

import sqlite3

import pytest

from app.ft_strategy._schema_sqlite import apply_sqlite_schema
from app.ft_strategy.report_validator import (
    ALLOWED_AUTHORING_STATES,
    DRAFT,
    FINAL,
    SQLITE_TRIGGER_SQL,
    install_sqlite_check_trigger,
    validate_report_final,
)


# ---------------------------------------------------------------------------
# validate_report_final (pure function)
# ---------------------------------------------------------------------------


class TestValidateFinal:
    def test_draft_passes_with_any_finding(self):
        result = validate_report_final(
            authoring_state="draft",
            reserved_finding="something or nothing",
            published_at=None,
        )
        assert result.ok
        assert result.state == "draft"
        assert result.errors == ()

    def test_draft_passes_with_null_finding(self):
        result = validate_report_final(
            authoring_state="draft",
            reserved_finding=None,
            published_at=None,
        )
        assert result.ok

    def test_final_with_valid_finding_passes(self):
        result = validate_report_final(
            authoring_state="final",
            reserved_finding="Sharpe 1.5 holds across all 4 regimes tested",
            published_at="2026-08-12T10:00:00Z",
        )
        assert result.ok

    def test_final_with_null_finding_fails(self):
        result = validate_report_final(
            authoring_state="final",
            reserved_finding=None,
            published_at="2026-08-12T10:00:00Z",
        )
        assert not result.ok
        assert any("reserved_finding" in e for e in result.errors)

    def test_final_with_empty_finding_fails(self):
        result = validate_report_final(
            authoring_state="final",
            reserved_finding="",
            published_at="2026-08-12T10:00:00Z",
        )
        assert not result.ok

    def test_final_with_whitespace_finding_fails(self):
        result = validate_report_final(
            authoring_state="final",
            reserved_finding="   ",
            published_at="2026-08-12T10:00:00Z",
        )
        assert not result.ok

    def test_final_with_todo_placeholder_fails(self):
        result = validate_report_final(
            authoring_state="final",
            reserved_finding="TODO: replace this",
            published_at="2026-08-12T10:00:00Z",
        )
        assert not result.ok
        assert any("TODO" in e for e in result.errors)

    def test_final_with_null_published_at_fails(self):
        result = validate_report_final(
            authoring_state="final",
            reserved_finding="Real finding here",
            published_at=None,
        )
        assert not result.ok
        assert any("published_at" in e for e in result.errors)

    def test_unknown_state_rejected(self):
        result = validate_report_final(
            authoring_state="published",
            reserved_finding="x",
            published_at="2026-08-12",
        )
        assert not result.ok
        assert any("authoring_state" in e for e in result.errors)

    def test_non_string_state_rejected(self):
        result = validate_report_final(
            authoring_state=42,  # type: ignore[arg-type]
            reserved_finding="x",
            published_at="2026-08-12",
        )
        assert not result.ok
        assert any("must be str" in e for e in result.errors)


class TestConstants:
    def test_allowed_states(self):
        assert ALLOWED_AUTHORING_STATES == ("draft", "final")

    def test_draft_value(self):
        assert DRAFT == "draft"

    def test_final_value(self):
        assert FINAL == "final"


# ---------------------------------------------------------------------------
# SQLite CHECK trigger (mirrors Postgres CHECK)
# ---------------------------------------------------------------------------


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    apply_sqlite_schema(c)
    install_sqlite_check_trigger(c)
    # Insert parent strategy so FK on ft_strategy_reports is satisfied
    c.execute(
        """
        INSERT INTO ft_strategies (id, name, idea_payload) VALUES
        ('s1', 'parent', '{}'),
        ('s2', 'parent2', '{}')
        """
    )
    c.commit()
    yield c
    c.close()


class TestSqliteTrigger:
    def test_draft_inserts_succeed(self, conn):
        conn.execute(
            """
            INSERT INTO ft_strategy_reports (id, strategy_id, version, authoring_state,
                                            reserved_finding, report_json)
            VALUES (?, 's1', 1, 'draft', NULL, '{}')
            """,
            ("r-draft-1",),
        )
        conn.commit()

    def test_final_with_valid_state_inserts(self, conn):
        conn.execute(
            """
            INSERT INTO ft_strategy_reports (id, strategy_id, version, authoring_state,
                                            reserved_finding, report_json, published_at)
            VALUES (?, 's1', 1, 'final', 'Sharpe 1.5 stable', '{}', '2026-08-12T10:00:00Z')
            """,
            ("r-final-1",),
        )
        conn.commit()

    def test_final_with_null_finding_rejected(self, conn):
        with pytest.raises(sqlite3.IntegrityError, match="ft_strategy_reports_final_check"):
            conn.execute(
                """
                INSERT INTO ft_strategy_reports (id, strategy_id, version, authoring_state,
                                                reserved_finding, report_json, published_at)
                VALUES (?, 's1', 1, 'final', NULL, '{}', '2026-08-12T10:00:00Z')
                """,
                ("r-final-bad-1",),
            )

    def test_final_with_todo_finding_rejected(self, conn):
        with pytest.raises(sqlite3.IntegrityError, match="ft_strategy_reports_final_check"):
            conn.execute(
                """
                INSERT INTO ft_strategy_reports (id, strategy_id, version, authoring_state,
                                                reserved_finding, report_json, published_at)
                VALUES (?, 's1', 1, 'final', 'TODO: write me', '{}', '2026-08-12T10:00:00Z')
                """,
                ("r-final-bad-2",),
            )

    def test_final_with_null_published_at_rejected(self, conn):
        with pytest.raises(sqlite3.IntegrityError, match="ft_strategy_reports_final_check"):
            conn.execute(
                """
                INSERT INTO ft_strategy_reports (id, strategy_id, version, authoring_state,
                                                reserved_finding, report_json, published_at)
                VALUES (?, 's1', 1, 'final', 'Real finding', '{}', NULL)
                """,
                ("r-final-bad-3",),
            )

    def test_update_to_final_with_null_finding_rejected(self, conn):
        # Insert draft row first
        conn.execute(
            """
            INSERT INTO ft_strategy_reports (id, strategy_id, version, authoring_state,
                                            reserved_finding, report_json)
            VALUES (?, 's1', 1, 'draft', NULL, '{}')
            """,
            ("r-promote-1",),
        )
        conn.commit()
        # Try to UPDATE to final WITHOUT setting reserved_finding (NULL)
        with pytest.raises(sqlite3.IntegrityError, match="ft_strategy_reports_final_check"):
            conn.execute(
                """
                UPDATE ft_strategy_reports
                   SET authoring_state = 'final', published_at = '2026-08-12'
                 WHERE id = 'r-promote-1'
                """
            )

    def test_update_to_valid_final_succeeds(self, conn):
        conn.execute(
            """
            INSERT INTO ft_strategy_reports (id, strategy_id, version, authoring_state,
                                            reserved_finding, report_json)
            VALUES (?, 's1', 1, 'draft', 'Initial draft finding', '{}')
            """,
            ("r-promote-2",),
        )
        conn.commit()
        conn.execute(
            """
            UPDATE ft_strategy_reports
               SET authoring_state = 'final',
                   reserved_finding = 'Final research conclusion: Sharpe holds across regimes',
                   published_at = '2026-08-12T10:00:00Z'
             WHERE id = 'r-promote-2'
            """
        )
        conn.commit()


class TestInstallTriggerIdempotent:
    def test_install_twice_no_error(self):
        c = sqlite3.connect(":memory:")
        try:
            apply_sqlite_schema(c)
            install_sqlite_check_trigger(c)
            install_sqlite_check_trigger(c)  # second call
            # Verify exists
            cur = c.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'ft_strategy_reports_final_%'"
            )
            triggers = {row[0] for row in cur.fetchall()}
            assert "ft_strategy_reports_final_insert" in triggers
            assert "ft_strategy_reports_final_update" in triggers
        finally:
            c.close()


class TestTriggerSqlFormat:
    def test_trigger_sql_has_correct_name(self):
        assert "ft_strategy_reports_final_check" in SQLITE_TRIGGER_SQL

    def test_trigger_sql_uses_new_pseudo_row(self):
        assert "NEW." in SQLITE_TRIGGER_SQL

    def test_trigger_sql_raises_abort(self):
        assert "RAISE(ABORT" in SQLITE_TRIGGER_SQL
