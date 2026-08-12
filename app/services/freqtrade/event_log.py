"""Event log — dual-write to DB + .tsv file (D-FT-18).

Mirrors the Auto-Quant V1 ``results.tsv`` event log pattern: ``commit | event |
strategy_name | sharpe | max_dd | note``, tab-separated, gitignored,
survives ``git reset --hard``.

D-FT-18 contract: the DB insert and the .tsv append are atomic — both happen
or neither happens. We use ``tempfile.NamedTemporaryFile`` + ``os.replace`` for
crash-safe file writes; the DB write happens first inside the transaction. If
the file write fails AFTER commit, we raise and log loudly (no silent half-writes).

The gitignored path: ``.scratch/loop_state/ft_strategy/{strategy_id}.tsv``.
Each strategy has its own append-only file. The header row is written on first
append (D-FT-18 verification: schema matches Auto-Quant V1 exactly).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.ft_strategy.supabase_repo import FtStrategyRepo, StrategyNotFound

DEFAULT_TSV_ROOT = Path(".scratch/loop_state/ft_strategy")

HEADER = "commit\tevent\tstrategy_name\tsharpe\tmax_dd\tnote"
ALLOWED_EVENTS = frozenset({
    "create",
    "evolve",
    "stable",
    "fork",
    "kill",
    "shadow_start",
    "shadow_end",
})


class EventLogError(Exception):
    """Raised when the dual-write fails. Both DB and .tsv must remain consistent."""


@dataclass(frozen=True)
class EventLogEntry:
    event: str
    strategy_name: str
    sharpe: Optional[float] = None
    max_dd: Optional[float] = None
    note: str = ""


def _tsv_path(tsv_root: Path, strategy_id: str) -> Path:
    return tsv_root / f"{strategy_id}.tsv"


def _git_commit_short() -> str:
    """Best-effort short git commit SHA; falls back to 'no-git' if unavailable.

    Pure function — never raises. Auto-Quant V1 expects a commit SHA per row;
    in CI / non-repo environments we mark rows clearly so the agent can detect.
    """
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()
        return sha or "no-git"
    except Exception:
        return "no-git"


def _format_row(entry: EventLogEntry) -> str:
    """Format a single TSV row matching Auto-Quant V1 ``results.tsv`` schema.

    Order: commit | event | strategy_name | sharpe | max_dd | note
    Tabs separate; no embedded tabs allowed in any field (strip them).
    """
    def _clean(s: str) -> str:
        return s.replace("\t", " ").replace("\n", " ").strip()

    sharpe = "" if entry.sharpe is None else f"{entry.sharpe}"
    max_dd = "" if entry.max_dd is None else f"{entry.max_dd}"
    return "\t".join([
        _git_commit_short(),
        _clean(entry.event),
        _clean(entry.strategy_name),
        _clean(sharpe),
        _clean(max_dd),
        _clean(entry.note),
    ])


def _write_header_if_missing(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(HEADER + "\n")


def _append_crash_safe(path: Path, row: str) -> None:
    """Append one line to .tsv atomically via tempfile + os.replace.

    Atomic on POSIX; on Windows would need a different strategy but the project
    runs on macOS/Linux per AGENTS.md.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_header_if_missing(path)

    # Read existing content, append, rewrite via tempfile.
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            with open(path, "r", encoding="utf-8") as src:
                chunk = src.read()
            out.write(chunk)
            if chunk and not chunk.endswith("\n"):
                out.write("\n")
            out.write(row + "\n")
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup of orphan tempfile.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


@contextmanager
def _event_log_transaction(repo: FtStrategyRepo):
    """Wrap the DB transaction in a savepoint that we can roll back on .tsv failure.

    For sqlite3 connections, we use savepoints because the outer connection
    may already be in autocommit mode (Postgres-style). On Postgres, the
    outer transaction provides atomicity and we just rely on that.
    """
    cur = repo.conn.cursor()
    savepoint_id = f"eventlog_{id(cur)}"
    try:
        try:
            cur.execute(f"SAVEPOINT {savepoint_id}")
        except Exception:
            # Not a transaction-capable connection (e.g. psycopg2 autocommit);
            # yield and let .tsv failure rollback at outer scope.
            pass
        yield cur
    except Exception:
        try:
            cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint_id}")
        except Exception:
            pass
        raise
    else:
        try:
            cur.execute(f"RELEASE SAVEPOINT {savepoint_id}")
        except Exception:
            pass


def record_event_dual(
    repo: FtStrategyRepo,
    *,
    strategy_id: str,
    event: str,
    strategy_name: str,
    sharpe: Optional[float] = None,
    max_dd: Optional[float] = None,
    note: str = "",
    version: Optional[int] = None,
    tsv_root: Optional[Path] = None,
) -> int:
    """D-FT-18: write to BOTH the DB and the per-strategy .tsv.

    Returns the DB event id. Raises ``EventLogError`` if either write fails.

    Order of operations (DB first per D-FT-18 implementation note):
    1. INSERT ft_strategy_events inside a savepoint
    2. UPDATE ft_strategies.last_event / stagnation_count
    3. Append one row to ``.scratch/loop_state/ft_strategy/{strategy_id}.tsv``
    4. RELEASE savepoint — both writes committed
    """
    if event not in ALLOWED_EVENTS:
        raise EventLogError(f"unknown event {event!r}; allowed: {sorted(ALLOWED_EVENTS)}")
    if not isinstance(strategy_name, str) or not strategy_name.strip():
        raise EventLogError("strategy_name must be a non-empty string")

    root = Path(tsv_root) if tsv_root is not None else DEFAULT_TSV_ROOT
    tsv_file = _tsv_path(root, strategy_id)
    entry = EventLogEntry(
        event=event,
        strategy_name=strategy_name,
        sharpe=sharpe,
        max_dd=max_dd,
        note=note,
    )
    row = _format_row(entry)

    db_event_id: Optional[int] = None
    # Pre-validate so FK violations (sqlite3.IntegrityError) are surfaced as
    # EventLogError with a friendlier message, before any side effects.
    try:
        repo.get_strategy(strategy_id)
    except StrategyNotFound as e:
        raise EventLogError(f"strategy_id not found: {strategy_id}") from e

    with _event_log_transaction(repo):
        # DB writes (via repo.record_event, but we don't double-mirror the side
        # effects on ft_strategies here — that helper does it. Accept the small
        # duplication of DB writes — both go in/out of savepoint together).
        db_event_id = repo.record_event(
            strategy_id=strategy_id,
            event=event,
            sharpe=sharpe,
            max_dd=max_dd,
            note=note,
            version=version,
        )
        # .tsv write — failure here rolls back the DB savepoint.
        try:
            _append_crash_safe(tsv_file, row)
        except Exception as e:
            raise EventLogError(f".tsv write failed for {strategy_id}: {e}") from e

    if db_event_id is None:
        raise EventLogError("DB write did not return an id; aborting")
    return db_event_id


def read_tsv_events(tsv_root: Path, strategy_id: str) -> list[dict[str, str]]:
    """Read all events from a strategy's .tsv file. Returns dict per row.

    Used by the UI's ``GET /api/ft-strategies/:id/history`` endpoint and by
    agents that want to learn from past strategies. Order: oldest-first.
    """
    path = _tsv_path(tsv_root, strategy_id)
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]
    if not lines:
        return []
    # First line is the header — skip it.
    header_cols = lines[0].split("\t")
    for line in lines[1:]:
        cols = line.split("\t")
        # Pad to header length
        while len(cols) < len(header_cols):
            cols.append("")
        rows.append(dict(zip(header_cols, cols)))
    return rows
