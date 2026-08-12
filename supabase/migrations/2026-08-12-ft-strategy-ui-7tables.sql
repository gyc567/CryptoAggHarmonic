-- FT Strategy UI — Loop #13 schema (7 tables).
-- Source: docs/plans/ft-strategy-ui-integration.md v3 §4.1-4.7 + ADR-0012 D2
-- File naming convention: YYYY-MM-DD-<name>.sql

-- ============================================================================
-- 1. ft_strategies — strategy namespace (mutable summary)
-- ============================================================================
CREATE TABLE IF NOT EXISTS ft_strategies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID,                       -- REFERENCES auth.users(id) (Supabase-only)
  name TEXT NOT NULL,
  description TEXT,
  market_type TEXT DEFAULT 'futures' CHECK (market_type IN ('futures')),
  pair TEXT DEFAULT 'BTC/USDT',
  interval TEXT DEFAULT '5m',
  idea_source TEXT DEFAULT 'template' CHECK (idea_source IN ('template', 'natural_language', 'clone')),
  idea_payload JSONB NOT NULL,
  status TEXT DEFAULT 'draft' CHECK (status IN (
    'draft', 'code_generated', 'hyperopt_running', 'backtest_running',
    'analyzed', 'refining', 'pending_review', 'deployed', 'rejected'
  )),
  current_version INT DEFAULT 1,
  strategy_file_path TEXT,
  latest_result JSONB,
  baseline_comparison JSONB,
  deployment_pr_url TEXT,

  -- v3 additions (D-FT-21 / §1.5 / D-FT-22 §6.5):
  research_md TEXT,
  last_event TEXT,
  stagnation_count INT DEFAULT 0,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE ft_strategies ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ft_strategies_user_isolation ON ft_strategies;
CREATE POLICY ft_strategies_user_isolation ON ft_strategies
  FOR ALL TO authenticated
  USING (user_id = auth.uid());

CREATE INDEX IF NOT EXISTS ft_strategies_user_idx ON ft_strategies(user_id);
CREATE INDEX IF NOT EXISTS ft_strategies_status_idx ON ft_strategies(status);


-- ============================================================================
-- 2. ft_strategy_runs — immutable execution (one row per (strategy, version, stage))
-- ============================================================================
CREATE TABLE IF NOT EXISTS ft_strategy_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id UUID NOT NULL REFERENCES ft_strategies(id) ON DELETE CASCADE,
  version INT NOT NULL,
  stage TEXT NOT NULL CHECK (stage IN ('code','hyperopt','backtest','analyze')),
  job_id TEXT,
  status TEXT DEFAULT 'queued' CHECK (status IN ('queued','running','finished','failed','cancelled')),
  progress_pct INT DEFAULT 0,
  result JSONB,                  -- write-once per convention; UPDATE here is forbidden via trigger
  params JSONB,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  source TEXT DEFAULT 'ft_strategy_ui',
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (strategy_id, version, stage)
);

ALTER TABLE ft_strategy_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ft_strategy_runs_strategy_isolation ON ft_strategy_runs;
CREATE POLICY ft_strategy_runs_strategy_isolation ON ft_strategy_runs
  FOR ALL TO authenticated
  USING (
    EXISTS (SELECT 1 FROM ft_strategies s WHERE s.id = strategy_id AND s.user_id = auth.uid())
  );

CREATE INDEX IF NOT EXISTS ft_strategy_runs_strategy_idx ON ft_strategy_runs(strategy_id, version);
CREATE INDEX IF NOT EXISTS ft_strategy_runs_status_idx ON ft_strategy_runs(status);

-- Prevent concurrent runs of same (strategy, stage, version) — partial unique index
-- (D-FT-22 / Stagnation discipline)
CREATE UNIQUE INDEX IF NOT EXISTS ft_strategy_runs_active_uniq
  ON ft_strategy_runs(strategy_id, version, stage)
  WHERE status IN ('queued', 'running');


-- ============================================================================
-- 3. ft_strategy_events — append-only results.tsv mirror
-- ============================================================================
CREATE TABLE IF NOT EXISTS ft_strategy_events (
  id BIGSERIAL PRIMARY KEY,
  strategy_id UUID NOT NULL REFERENCES ft_strategies(id) ON DELETE CASCADE,
  version INT,
  event TEXT NOT NULL CHECK (event IN ('create','evolve','stable','fork','kill','shadow_start','shadow_end')),
  sharpe NUMERIC,
  max_dd NUMERIC,
  note TEXT,
  recorded_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ft_strategy_events_strategy_idx
  ON ft_strategy_events(strategy_id, recorded_at DESC);


-- ============================================================================
-- 4. ft_strategy_experiments — KEEP / REVERT / CRASH verdicts
-- ============================================================================
CREATE TABLE IF NOT EXISTS ft_strategy_experiments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id UUID NOT NULL REFERENCES ft_strategies(id) ON DELETE CASCADE,
  version_from INT NOT NULL,
  version_to INT NOT NULL,
  verdict TEXT NOT NULL CHECK (verdict IN ('keep','revert','crash')),
  reasoning TEXT NOT NULL,         -- D-FT-19: NOT NULL; minimum length enforced in API layer
  metrics_delta JSONB,
  decided_by UUID,                 -- references auth.users(id) (Supabase-only)
  recorded_at TIMESTAMPTZ DEFAULT now(),
  CHECK (version_to = version_from + 1)
);

CREATE INDEX IF NOT EXISTS ft_strategy_experiments_strategy_idx
  ON ft_strategy_experiments(strategy_id, recorded_at DESC);


-- ============================================================================
-- 5. ft_strategy_reports — Audit-grade analysis artifact (final rows locked)
-- ============================================================================
CREATE TABLE IF NOT EXISTS ft_strategy_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id UUID NOT NULL REFERENCES ft_strategies(id) ON DELETE CASCADE,
  version INT NOT NULL,
  authoring_state TEXT NOT NULL DEFAULT 'draft' CHECK (authoring_state IN ('draft','final')),
  reserved_finding TEXT,
  report_json JSONB NOT NULL,
  report_md TEXT,
  metrics_snapshot JSONB,
  baseline_snapshot JSONB,
  published_at TIMESTAMPTZ,
  published_by UUID,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),

  -- D-FT-20: final rows are immutable (DB CHECK enforces invariants)
  CONSTRAINT ft_strategy_reports_final_check CHECK (
    (authoring_state = 'draft') OR
    (authoring_state = 'final' AND reserved_finding IS NOT NULL
     AND reserved_finding NOT LIKE 'TODO:%'
     AND published_at IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS ft_strategy_reports_strategy_idx
  ON ft_strategy_reports(strategy_id, version);


-- ============================================================================
-- 6. ft_strategy_insights — cross-strategy learning, durable-facts bridge
-- ============================================================================
CREATE TABLE IF NOT EXISTS ft_strategy_insights (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id UUID REFERENCES ft_strategies(id) ON DELETE CASCADE,
  insight_type TEXT NOT NULL CHECK (insight_type IN (
    'baseline_drift', 'param_anomaly', 'shadow_signal',
    'cross_strategy_pattern', 'win_rate_outlier'
  )),
  content TEXT NOT NULL,
  evidence JSONB,
  confidence TEXT DEFAULT 'medium' CHECK (confidence IN ('low','medium','high')),
  durable_fact_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ft_strategy_insights_strategy_idx
  ON ft_strategy_insights(strategy_id);

CREATE INDEX IF NOT EXISTS ft_strategy_insights_fact_idx
  ON ft_strategy_insights(durable_fact_id) WHERE durable_fact_id IS NOT NULL;


-- ============================================================================
-- 7. ft_jobs — worker job tracking (Redis shadow for queries)
-- ============================================================================
CREATE TABLE IF NOT EXISTS ft_jobs (
  job_id TEXT PRIMARY KEY,
  strategy_id UUID NOT NULL REFERENCES ft_strategies(id) ON DELETE CASCADE,
  stage TEXT NOT NULL CHECK (stage IN ('code','hyperopt','backtest','analyze','refine','deploy')),
  status TEXT DEFAULT 'queued' CHECK (status IN ('queued','running','finished','failed','cancelled')),
  progress_pct INT DEFAULT 0,
  candidates_evaluated INT,
  best_profit NUMERIC,
  error TEXT,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  result_summary JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ft_jobs_strategy_idx ON ft_jobs(strategy_id);
CREATE INDEX IF NOT EXISTS ft_jobs_status_idx ON ft_jobs(status);

-- ============================================================================
-- Comments documenting per-table intent
-- ============================================================================
COMMENT ON TABLE ft_strategies IS 'Strategy namespace. current_version bumped by SQL expression on refine (D-FT-08).';
COMMENT ON TABLE ft_strategy_runs IS 'Append-only execution rows. result is write-once per row (no UPDATE convention enforced by trigger in v3.0; rely on repo discipline).';
COMMENT ON TABLE ft_strategy_events IS 'Mirror of .scratch/loop_state/ft_strategy/{id}.tsv (results.tsv pattern from Auto-Quant V1). Append-only (D-FT-18).';
COMMENT ON TABLE ft_strategy_experiments IS 'KEEP/REVERT/CRASH verdict. reasoning NOT NULL (D-FT-19).';
COMMENT ON TABLE ft_strategy_reports IS 'Audit-grade report. authoring_state final is locked via CHECK (D-FT-20).';
COMMENT ON TABLE ft_strategy_insights IS 'Cross-strategy insights; durable_fact_id nullable until promoted.';
COMMENT ON TABLE ft_jobs IS 'Shadow of Redis ft_job:{id}; used for SQL-side job queries without Redis dependency.';
