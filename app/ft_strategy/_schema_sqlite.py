"""SQLite-compatible DDL for FT Strategy UI 7 tables.

Supabase Postgres DDL lives in ``supabase/migrations/``; this file is the
SQLite equivalent for dev / CI test runs (no Supabase connection). The two
must stay in sync — see cross-check at CI time.

Differences from Postgres DDL:
- Drops ``gen_random_uuid()`` (use plain TEXT primary keys or hex strings).
- Drops RLS policies (SQLite has no RLS; per-user isolation is enforced at
  the app layer by passing user_id explicitly into WHERE clauses).
- Drops TIMESTAMPTZ / JSONB type annotations; SQLite stores TEXT.
- Drops TRIGGER / CONSTRAINT features that don't translate.
"""

from __future__ import annotations

SQLITE_DDL: tuple[str, ...] = (
    # 1. strategies
    """
    CREATE TABLE IF NOT EXISTS ft_strategies (
      id TEXT PRIMARY KEY,
      user_id TEXT,
      name TEXT NOT NULL,
      description TEXT,
      market_type TEXT DEFAULT 'futures',
      pair TEXT DEFAULT 'BTC/USDT',
      interval TEXT DEFAULT '5m',
      idea_source TEXT DEFAULT 'template',
      idea_payload TEXT NOT NULL,
      status TEXT DEFAULT 'draft',
      current_version INTEGER DEFAULT 1,
      strategy_file_path TEXT,
      latest_result TEXT,
      baseline_comparison TEXT,
      deployment_pr_url TEXT,
      research_md TEXT,
      last_event TEXT,
      stagnation_count INTEGER DEFAULT 0,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS ft_strategies_user_idx ON ft_strategies(user_id);",
    "CREATE INDEX IF NOT EXISTS ft_strategies_status_idx ON ft_strategies(status);",
    # 2. runs
    """
    CREATE TABLE IF NOT EXISTS ft_strategy_runs (
      id TEXT PRIMARY KEY,
      strategy_id TEXT NOT NULL REFERENCES ft_strategies(id) ON DELETE CASCADE,
      version INTEGER NOT NULL,
      stage TEXT NOT NULL,
      job_id TEXT,
      status TEXT DEFAULT 'queued',
      progress_pct INTEGER DEFAULT 0,
      result TEXT,
      params TEXT,
      started_at TEXT,
      finished_at TEXT,
      source TEXT DEFAULT 'ft_strategy_ui',
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      UNIQUE (strategy_id, version, stage)
    );
    """,
    "CREATE INDEX IF NOT EXISTS ft_strategy_runs_strategy_idx ON ft_strategy_runs(strategy_id, version);",
    "CREATE INDEX IF NOT EXISTS ft_strategy_runs_status_idx ON ft_strategy_runs(status);",
    # 3. events
    """
    CREATE TABLE IF NOT EXISTS ft_strategy_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      strategy_id TEXT NOT NULL REFERENCES ft_strategies(id) ON DELETE CASCADE,
      version INTEGER,
      event TEXT NOT NULL,
      sharpe REAL,
      max_dd REAL,
      note TEXT,
      recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS ft_strategy_events_strategy_idx ON ft_strategy_events(strategy_id, recorded_at DESC);",
    # 4. experiments
    """
    CREATE TABLE IF NOT EXISTS ft_strategy_experiments (
      id TEXT PRIMARY KEY,
      strategy_id TEXT NOT NULL REFERENCES ft_strategies(id) ON DELETE CASCADE,
      version_from INTEGER NOT NULL,
      version_to INTEGER NOT NULL,
      verdict TEXT NOT NULL,
      reasoning TEXT NOT NULL,
      metrics_delta TEXT,
      decided_by TEXT,
      recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS ft_strategy_experiments_strategy_idx ON ft_strategy_experiments(strategy_id, recorded_at DESC);",
    # 5. reports
    """
    CREATE TABLE IF NOT EXISTS ft_strategy_reports (
      id TEXT PRIMARY KEY,
      strategy_id TEXT NOT NULL REFERENCES ft_strategies(id) ON DELETE CASCADE,
      version INTEGER NOT NULL,
      authoring_state TEXT NOT NULL DEFAULT 'draft',
      reserved_finding TEXT,
      report_json TEXT NOT NULL,
      report_md TEXT,
      metrics_snapshot TEXT,
      baseline_snapshot TEXT,
      published_at TEXT,
      published_by TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS ft_strategy_reports_strategy_idx ON ft_strategy_reports(strategy_id, version);",
    # 6. insights
    """
    CREATE TABLE IF NOT EXISTS ft_strategy_insights (
      id TEXT PRIMARY KEY,
      strategy_id TEXT REFERENCES ft_strategies(id) ON DELETE CASCADE,
      insight_type TEXT NOT NULL,
      content TEXT NOT NULL,
      evidence TEXT,
      confidence TEXT DEFAULT 'medium',
      durable_fact_id TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS ft_strategy_insights_strategy_idx ON ft_strategy_insights(strategy_id);",
    "CREATE INDEX IF NOT EXISTS ft_strategy_insights_fact_idx ON ft_strategy_insights(durable_fact_id) WHERE durable_fact_id IS NOT NULL;",
    # 7. jobs
    """
    CREATE TABLE IF NOT EXISTS ft_jobs (
      job_id TEXT PRIMARY KEY,
      strategy_id TEXT NOT NULL REFERENCES ft_strategies(id) ON DELETE CASCADE,
      stage TEXT NOT NULL,
      status TEXT DEFAULT 'queued',
      progress_pct INTEGER DEFAULT 0,
      candidates_evaluated INTEGER,
      best_profit REAL,
      error TEXT,
      started_at TEXT,
      finished_at TEXT,
      result_summary TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS ft_jobs_strategy_idx ON ft_jobs(strategy_id);",
    "CREATE INDEX IF NOT EXISTS ft_jobs_status_idx ON ft_jobs(status);",
)


def apply_sqlite_schema(conn) -> None:
    """Apply the 7-table SQLite DDL to ``conn``.

    ``conn`` is a ``sqlite3.Connection`` (or compatible DB-API 2.0 connection).
    """
    # Required for ON DELETE CASCADE / FK enforcement in SQLite.
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()
    for stmt in SQLITE_DDL:
        cur.execute(stmt)
    conn.commit()
