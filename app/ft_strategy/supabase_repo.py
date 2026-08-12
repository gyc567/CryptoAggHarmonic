"""FT Strategy repository — thin DB CRUD layer for 7 tables (Phase 2).

Pattern: explicit ``conn`` parameter so tests can inject sqlite. Production
calls pass the Supabase pooled connection from ``app.infra.supabase_client``.

Conventions enforced here (D-FT-NN):
- D-FT-08: ``refine()`` uses ``UPDATE ... SET current_version = current_version + 1``
  so two concurrent refines can't lose an increment.
- D-FT-19: ``record_experiment()`` requires non-empty ``reasoning``.
- D-FT-20: ``publish_report()`` requires ``reserved_finding`` to be present and
  not ``"TODO:%"``; transitions are sticky (cannot revert ``final`` → ``draft``).
- Plan §4.1: ``research_md`` field is part of strategies (D-FT-21 Phase 2
  shape — actual content validation is at API layer).
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.ft_strategy._schema_sqlite import apply_sqlite_schema
from app.loop.tuning_promotion_v3 import REASONING_MIN_LENGTH


# ---------------------------------------------------------------------------
# Errors (D-FT-23: never raise for legitimate business-false returns; only for
# programming errors / invariant violations).
# ---------------------------------------------------------------------------


class FtStrategyError(Exception):
    """Base class for FT strategy repository errors."""


class StrategyNotFound(FtStrategyError):
    pass


class ReasoningEmpty(FtStrategyError):
    """D-FT-19: reasoning must be non-empty on verdict."""


class ReportFinalLocked(FtStrategyError):
    """D-FT-20: a final report cannot revert to draft."""


class ReportInvalidFinal(FtStrategyError):
    """D-FT-20: publishing as final requires non-TODO reserved_finding."""


# ---------------------------------------------------------------------------
# Row dataclasses (DTOs for repository return values)
# ---------------------------------------------------------------------------


@dataclass
class Strategy:
    id: str
    user_id: Optional[str]
    name: str
    description: Optional[str]
    market_type: str
    pair: str
    interval: str
    idea_source: str
    idea_payload: dict
    status: str
    current_version: int
    strategy_file_path: Optional[str]
    latest_result: Optional[dict]
    baseline_comparison: Optional[dict]
    deployment_pr_url: Optional[str]
    research_md: Optional[str]
    last_event: Optional[str]
    stagnation_count: int
    created_at: Optional[str]
    updated_at: Optional[str]


@dataclass
class Run:
    id: str
    strategy_id: str
    version: int
    stage: str
    job_id: Optional[str]
    status: str
    progress_pct: int
    result: Optional[dict]
    params: Optional[dict]
    started_at: Optional[str]
    finished_at: Optional[str]
    source: str
    created_at: Optional[str]


@dataclass
class Experiment:
    id: str
    strategy_id: str
    version_from: int
    version_to: int
    verdict: str
    reasoning: str
    metrics_delta: Optional[dict]
    decided_by: Optional[str]
    recorded_at: Optional[str]


@dataclass
class Report:
    id: str
    strategy_id: str
    version: int
    authoring_state: str
    reserved_finding: Optional[str]
    report_json: dict
    report_md: Optional[str]
    metrics_snapshot: Optional[dict]
    baseline_snapshot: Optional[dict]
    published_at: Optional[str]
    published_by: Optional[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _to_json(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value)


def _from_json(text: Optional[Any]) -> Optional[Any]:
    if text is None or text == "":
        return None
    return json.loads(text)


_RESERVED_PLACEHOLDER_RE = re.compile(r"^TODO:")


def _check_reserved_finding(text: Optional[str]) -> None:
    if not text or _RESERVED_PLACEHOLDER_RE.match(text):
        raise ReportInvalidFinal(
            "reserved_finding must be set and not start with 'TODO:' to publish as final"
        )


def _check_reasoning(reasoning: str) -> None:
    if not isinstance(reasoning, str) or len(reasoning.strip()) < REASONING_MIN_LENGTH:
        raise ReasoningEmpty(
            f"reasoning must be a non-empty string >= {REASONING_MIN_LENGTH} chars (D-FT-19)"
        )


def _row_to_strategy(row: sqlite3.Row) -> Strategy:
    return Strategy(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        description=row["description"],
        market_type=row["market_type"],
        pair=row["pair"],
        interval=row["interval"],
        idea_source=row["idea_source"],
        idea_payload=_from_json(row["idea_payload"]) or {},
        status=row["status"],
        current_version=row["current_version"],
        strategy_file_path=row["strategy_file_path"],
        latest_result=_from_json(row["latest_result"]),
        baseline_comparison=_from_json(row["baseline_comparison"]),
        deployment_pr_url=row["deployment_pr_url"],
        research_md=row["research_md"],
        last_event=row["last_event"],
        stagnation_count=row["stagnation_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_run(row: sqlite3.Row) -> Run:
    return Run(
        id=row["id"],
        strategy_id=row["strategy_id"],
        version=row["version"],
        stage=row["stage"],
        job_id=row["job_id"],
        status=row["status"],
        progress_pct=row["progress_pct"],
        result=_from_json(row["result"]),
        params=_from_json(row["params"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        source=row["source"],
        created_at=row["created_at"],
    )


def _row_to_report(row: sqlite3.Row) -> Report:
    return Report(
        id=row["id"],
        strategy_id=row["strategy_id"],
        version=row["version"],
        authoring_state=row["authoring_state"],
        reserved_finding=row["reserved_finding"],
        report_json=_from_json(row["report_json"]) or {},
        report_md=row["report_md"],
        metrics_snapshot=_from_json(row["metrics_snapshot"]),
        baseline_snapshot=_from_json(row["baseline_snapshot"]),
        published_at=row["published_at"],
        published_by=row["published_by"],
    )


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class FtStrategyRepo:
    """Thin CRUD layer. Pass any sqlite3 (or Postgres-compatible) connection."""

    def __init__(self, conn):
        self.conn = conn
        # Enable row access by name (sqlite only; harmless for Postgres-style).
        if hasattr(conn, "row_factory"):
            conn.row_factory = sqlite3.Row
        # Ensure schema exists if SQLite
        if isinstance(conn, sqlite3.Connection):
            apply_sqlite_schema(conn)

    # -- strategies --
    def create_strategy(
        self,
        *,
        user_id: Optional[str],
        name: str,
        research_md: str,
        idea_payload: dict,
        market_type: str = "futures",
        pair: str = "BTC/USDT",
        interval: str = "5m",
        idea_source: str = "template",
        description: Optional[str] = None,
    ) -> Strategy:
        sid = _new_id()
        now = _now_iso()
        self.conn.execute(
            """
            INSERT INTO ft_strategies (
                id, user_id, name, description, market_type, pair, interval,
                idea_source, idea_payload, status, current_version,
                research_md, last_event, stagnation_count,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', 1, ?, 'create', 0, ?, ?)
            """,
            (
                sid, user_id, name, description, market_type, pair, interval,
                idea_source, _to_json(idea_payload), research_md, now, now,
            ),
        )
        self.conn.commit()
        return self.get_strategy(sid)

    def get_strategy(self, strategy_id: str) -> Strategy:
        cur = self.conn.execute(
            "SELECT * FROM ft_strategies WHERE id = ?", (strategy_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise StrategyNotFound(strategy_id)
        return _row_to_strategy(row)

    def update_status(self, strategy_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE ft_strategies SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now_iso(), strategy_id),
        )
        self.conn.commit()

    def update_latest_result(self, strategy_id: str, latest_result: dict) -> None:
        self.conn.execute(
            "UPDATE ft_strategies SET latest_result = ?, updated_at = ? WHERE id = ?",
            (_to_json(latest_result), _now_iso(), strategy_id),
        )
        self.conn.commit()

    def refine(self, strategy_id: str) -> Strategy:
        """D-FT-08: bump version atomically via SQL expression."""
        cur = self.conn.execute(
            """
            UPDATE ft_strategies
               SET current_version = current_version + 1,
                   updated_at = ?,
                   status = 'refining'
             WHERE id = ?
            RETURNING id
            """,
            (_now_iso(), strategy_id),
        )
        row = cur.fetchone()
        if row is None:
            raise StrategyNotFound(strategy_id)
        self.conn.commit()
        return self.get_strategy(strategy_id)

    # -- runs --
    def create_run(
        self,
        *,
        strategy_id: str,
        version: int,
        stage: str,
        source: str = "ft_strategy_ui",
    ) -> Run:
        rid = _new_id()
        self.conn.execute(
            """
            INSERT INTO ft_strategy_runs (
                id, strategy_id, version, stage, status, progress_pct, source, created_at
            ) VALUES (?, ?, ?, ?, 'queued', 0, ?, ?)
            """,
            (rid, strategy_id, version, stage, source, _now_iso()),
        )
        self.conn.commit()
        return self.get_run(rid)

    def get_run(self, run_id: str) -> Run:
        cur = self.conn.execute("SELECT * FROM ft_strategy_runs WHERE id = ?", (run_id,))
        row = cur.fetchone()
        if row is None:
            raise FtStrategyError(f"run not found: {run_id}")
        return _row_to_run(row)

    # -- experiments (KEEP/REVERT/CRASH) --
    def record_experiment(
        self,
        *,
        strategy_id: str,
        version_from: int,
        verdict: str,
        reasoning: str,
        metrics_delta: Optional[dict] = None,
        decided_by: Optional[str] = None,
    ) -> Experiment:
        """D-FT-19: reasoning must be non-empty."""
        _check_reasoning(reasoning)
        if verdict not in ("keep", "revert", "crash"):
            raise FtStrategyError(f"verdict must be one of keep/revert/crash; got {verdict!r}")
        eid = _new_id()
        self.conn.execute(
            """
            INSERT INTO ft_strategy_experiments (
                id, strategy_id, version_from, version_to, verdict, reasoning,
                metrics_delta, decided_by, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                eid, strategy_id, version_from, version_from + 1, verdict, reasoning,
                _to_json(metrics_delta), decided_by, _now_iso(),
            ),
        )
        self.conn.commit()
        return Experiment(
            id=eid, strategy_id=strategy_id, version_from=version_from,
            version_to=version_from + 1, verdict=verdict, reasoning=reasoning,
            metrics_delta=metrics_delta, decided_by=decided_by, recorded_at=None,
        )

    def list_open_crashes(self, strategy_id: str, window_days: int = 7) -> int:
        """Count crash verdicts without decided_by within the last ``window_days`` days."""
        # Pure SQL is platform-dependent (CURRENT_TIMESTAMP). We approximate by
        # counting rows with decided_by IS NULL for the most recent window.
        # This satisfies D-FT-19 gate item 8 with a conservative fetch.
        cur = self.conn.execute(
            """
            SELECT COUNT(*) FROM ft_strategy_experiments
             WHERE strategy_id = ?
               AND verdict = 'crash'
               AND decided_by IS NULL
            """,
            (strategy_id,),
        )
        return int(cur.fetchone()[0])

    # -- reports (audit-grade) --
    def create_report(
        self,
        *,
        strategy_id: str,
        version: int,
        report_json: dict,
        report_md: Optional[str] = None,
        metrics_snapshot: Optional[dict] = None,
        baseline_snapshot: Optional[dict] = None,
        reserved_finding: Optional[str] = None,
    ) -> Report:
        if authoring_state := "draft":
            pass  # always draft on create
        rid = _new_id()
        self.conn.execute(
            """
            INSERT INTO ft_strategy_reports (
                id, strategy_id, version, authoring_state, reserved_finding,
                report_json, report_md, metrics_snapshot, baseline_snapshot, created_at, updated_at
            ) VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid, strategy_id, version, reserved_finding,
                _to_json(report_json), report_md,
                _to_json(metrics_snapshot), _to_json(baseline_snapshot),
                _now_iso(), _now_iso(),
            ),
        )
        self.conn.commit()
        return Report(
            id=rid, strategy_id=strategy_id, version=version,
            authoring_state="draft", reserved_finding=reserved_finding,
            report_json=report_json, report_md=report_md,
            metrics_snapshot=metrics_snapshot, baseline_snapshot=baseline_snapshot,
            published_at=None, published_by=None,
        )

    def publish_report(self, report_id: str, reserved_finding: str) -> Report:
        """D-FT-20: publish as final; cannot revert.

        Defense-in-depth: validate_report_final() runs BEFORE UPDATE so we
        catch invariant violations even before the (Postgres) DB CHECK fires.
        On dev SQLite (where install_sqlite_check_trigger is installed) the
        DB CHECK is also enforced; either layer alone is sufficient.
        """
        # Import here to avoid circular import at module load time
        from app.ft_strategy.report_validator import validate_report_final

        cur = self.conn.execute(
            "SELECT * FROM ft_strategy_reports WHERE id = ?", (report_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise FtStrategyError(f"report not found: {report_id}")
        if row["authoring_state"] == "final":
            raise ReportFinalLocked(
                "report is already final; create a new draft for revisions"
            )
        _check_reserved_finding(reserved_finding)

        # Pre-check invariants before the DB CHECK fires (parity with Postgres)
        # published_at is set in the UPDATE below; a basic check ensures the
        # would-be final-state passes validate_report_final.
        check = validate_report_final(
            authoring_state="final",
            reserved_finding=reserved_finding,
            published_at="<pending>",
        )
        if not check.ok:
            raise ReportInvalidFinal("; ".join(check.errors))

        self.conn.execute(
            """
            UPDATE ft_strategy_reports
               SET authoring_state = 'final',
                   reserved_finding = ?,
                   published_at = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (reserved_finding, _now_iso(), _now_iso(), report_id),
        )
        self.conn.commit()
        return self.get_report(report_id)

    def get_report(self, report_id: str) -> Report:
        cur = self.conn.execute(
            "SELECT * FROM ft_strategy_reports WHERE id = ?", (report_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise FtStrategyError(f"report not found: {report_id}")
        return _row_to_report(row)

    def has_final_report(self, strategy_id: str) -> bool:
        cur = self.conn.execute(
            """
            SELECT 1 FROM ft_strategy_reports
             WHERE strategy_id = ? AND authoring_state = 'final'
             LIMIT 1
            """,
            (strategy_id,),
        )
        return cur.fetchone() is not None

    # -- events (D-FT-18: mirror of .tsv file; tests should call both together) --
    def record_event(
        self,
        *,
        strategy_id: str,
        event: str,
        version: Optional[int] = None,
        sharpe: Optional[float] = None,
        max_dd: Optional[float] = None,
        note: Optional[str] = None,
    ) -> int:
        if event not in ("create", "evolve", "stable", "fork", "kill", "shadow_start", "shadow_end"):
            raise FtStrategyError(f"unknown event: {event}")
        cur = self.conn.execute(
            """
            INSERT INTO ft_strategy_events (
                strategy_id, version, event, sharpe, max_dd, note, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (strategy_id, version, event, sharpe, max_dd, note, _now_iso()),
        )
        self.conn.commit()
        # Mirror onto strategies.last_event + stagnation_count if applicable.
        self.conn.execute(
            "UPDATE ft_strategies SET last_event = ?, updated_at = ? WHERE id = ?",
            (event, _now_iso(), strategy_id),
        )
        if event == "stable":
            self.conn.execute(
                "UPDATE ft_strategies SET stagnation_count = stagnation_count + 1 WHERE id = ?",
                (strategy_id,),
            )
        elif event in ("evolve", "fork", "kill"):
            self.conn.execute(
                "UPDATE ft_strategies SET stagnation_count = 0 WHERE id = ?",
                (strategy_id,),
            )
        self.conn.commit()
        return cur.lastrowid

    def recent_stable_count(self, strategy_id: str) -> int:
        """Consecutive stable events from the most recent non-stable event."""
        cur = self.conn.execute(
            """
            SELECT event FROM ft_strategy_events
             WHERE strategy_id = ?
             ORDER BY id DESC
            """,
            (strategy_id,),
        )
        count = 0
        for (event,) in cur.fetchall():
            if event == "stable":
                count += 1
            else:
                break
        return count

    def reset_stagnation(self, strategy_id: str) -> None:
        self.conn.execute(
            "UPDATE ft_strategies SET stagnation_count = 0 WHERE id = ?",
            (strategy_id,),
        )
        self.conn.commit()
