// FT Strategy UI — shared types
// Mirrors app/domain/ft_strategy_schemas.py and app/api/ft_strategy_routes.py

export type FtStatus =
  | "draft"
  | "code_generated"
  | "hyperopt_running"
  | "backtest_running"
  | "analyzed"
  | "refining"
  | "pending_review"
  | "deployed"
  | "rejected";

export type IdeaSource = "template" | "natural_language" | "clone";

export type Stage = "code" | "hyperopt" | "backtest" | "analyze";

export type RunStatus = "queued" | "running" | "finished" | "failed" | "cancelled";

export type EventType =
  | "create"
  | "evolve"
  | "stable"
  | "fork"
  | "kill"
  | "shadow_start"
  | "shadow_end";

export type Verdict = "keep" | "revert" | "crash";

export type InsightType =
  | "baseline_drift"
  | "param_anomaly"
  | "shadow_signal"
  | "cross_strategy_pattern"
  | "win_rate_outlier";

export type AuthoringState = "draft" | "final";

// ─── Strategy ────────────────────────────────────────────────────────────────

export interface FtStrategy {
  id: string;
  user_id: string;
  name: string;
  description?: string;
  market_type: "futures";
  pair: string;
  interval: string;
  idea_source: IdeaSource;
  idea_payload: Record<string, unknown>;
  research_md?: string;
  last_event?: EventType;
  stagnation_count: number;
  status: FtStatus;
  current_version: number;
  strategy_file_path?: string;
  latest_result?: BacktestResult;
  baseline_comparison?: BaselineComparison;
  deployment_pr_url?: string;
  created_at: string;
  updated_at: string;
}

export interface BaselineComparison {
  drawdown_ok: boolean;
  drawdown_pct: number;
  baseline_drawdown_pct: number;
  calmar_ok: boolean;
  calmar: number;
  baseline_calmar: number;
}

// ─── Run ───────────────────────────────────────────────────────────────────

export interface FtStrategyRun {
  id: string;
  strategy_id: string;
  version: number;
  stage: Stage;
  job_id?: string;
  status: RunStatus;
  progress_pct: number;
  result?: BacktestResult;
  params?: Record<string, unknown>;
  started_at?: string;
  finished_at?: string;
  source: string;
  created_at: string;
}

// ─── Backtest Result ────────────────────────────────────────────────────────

export interface BacktestResult {
  run_id: string;
  strategy_id: string;
  version: number;
  aggregate: AggregateMetrics;
  per_pair: Record<string, PairMetrics>;
  per_timerange: Record<string, TimerangeMetrics>;
  raw_blocks: string;
  baseline_comparison?: BaselineComparison;
  promotion_checklist?: string[];
}

export interface AggregateMetrics {
  sharpe: number;
  max_dd: number;
  calmar: number;
  win_rate: number;
  profit_pct: number;
  trades: number;
  robust_sharpe_min: number;
}

export interface PairMetrics {
  sharpe: number;
  max_dd: number;
  trades: number;
  profit_pct: number;
}

export interface TimerangeMetrics {
  sharpe: number;
  max_dd: number;
}

// ─── Events ─────────────────────────────────────────────────────────────────

export interface FtStrategyEvent {
  id: number;
  strategy_id: string;
  version?: number;
  event: EventType;
  sharpe?: number;
  max_dd?: number;
  note?: string;
  recorded_at: string;
}

// ─── Experiments ──────────────────────────────────────────────────────────

export interface FtStrategyExperiment {
  id: string;
  strategy_id: string;
  version_from: number;
  version_to: number;
  verdict: Verdict;
  reasoning: string;
  metrics_delta?: {
    sharpe_from: number;
    sharpe_to: number;
    dd_from: number;
    dd_to: number;
  };
  decided_by?: string;
  recorded_at: string;
}

// ─── Reports ───────────────────────────────────────────────────────────────

export interface FtStrategyReport {
  id: string;
  strategy_id: string;
  version: number;
  authoring_state: AuthoringState;
  reserved_finding?: string;
  report_json: BacktestResult;
  report_md?: string;
  metrics_snapshot?: Record<string, unknown>;
  baseline_snapshot?: Record<string, unknown>;
  published_at?: string;
  published_by?: string;
  created_at: string;
  updated_at: string;
}

// ─── Insights ─────────────────────────────────────────────────────────────

export interface FtStrategyInsight {
  id: string;
  strategy_id: string;
  insight_type: InsightType;
  content: string;
  evidence?: Record<string, unknown>;
  confidence: "low" | "medium" | "high";
  durable_fact_id?: string;
  created_at: string;
}

// ─── Capabilities / Orient ─────────────────────────────────────────────────

export interface FtCapabilities {
  endpoints: string[];
  queue_names: string[];
  constants: {
    MCP_TIMEOUT_SECONDS: number;
    MAX_BACKTEST_PER_GEN: number;
    STAGNATION_ROUNDS: number;
  };
  hard_limits: {
    strategies_hard_cap: number | null;
    max_hyperopt_minutes: number;
    max_backtest_per_gen: number;
  };
}

export interface OrientEntry {
  strategy_id: string;
  current_stage?: Stage;
  last_run_id?: string;
  stagnation_count: number;
  next_action: {
    type: "wait_backtest" | "refine" | "apply_deploy_pr" | "complete_shadow" | "none";
    reason: string;
    deadline?: string;
  };
  hard_blockers: string[];
}

export interface FtOrient {
  current_user_strategies: number;
  stagnation_hits: { strategy_id: string; count: number }[];
  blockers: string[];
  next_actions: OrientEntry[];
  loop_health: {
    active_jobs: number;
    pending_review: number;
    deployed: number;
  };
}

// ─── Promotion ─────────────────────────────────────────────────────────────

export interface PromotionChecklist {
  all_passed: boolean;
  items: PromotionCheckItem[];
}

export interface PromotionCheckItem {
  key: string;
  label: string;
  passed: boolean;
  detail?: string;
}

// ─── Create Request ─────────────────────────────────────────────────────────

export interface CreateFtStrategyRequest {
  name: string;
  description?: string;
  market_type?: "futures";
  pair?: string;
  interval?: string;
  idea_source: IdeaSource;
  idea_payload: Record<string, unknown>;
  research_md: string; // D-FT-21: ≥ 200 chars, required
}

export interface RefineRequest {
  params_delta: Record<string, unknown>;
  intended_event?: "evolve" | "fork" | "kill";
  reasoning?: string; // required if fork/kill or stagnation >= 3
}
