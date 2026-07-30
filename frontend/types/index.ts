export type Market = "binance" | "yahoo";
export type Interval = "15m" | "1h" | "4h" | "1d" | "1w";
export type AnalysisType = "auto" | "forming" | "formed" | "divergence";
export type AnalysisStatus =
  | "created"
  | "validating"
  | "fetching_market_data"
  | "detecting_patterns"
  | "interpreting"
  | "completed"
  | "no_result"
  | "failed_upstream"
  | "failed_model"
  | "failed_chart"
  | "rejected";

export interface UserProfile {
  id: string;
  email: string;
  display_name?: string;
  role: "user" | "admin";
  status: "active" | "suspended";
  daily_quota: number;
  used_quota: number;
  last_seen_at?: string;
  created_at?: string;
}

export interface AnalyzeRequest {
  market: Market;
  symbol: string;
  interval: Interval;
  analysis_type: AnalysisType;
  limit_to?: number;
  percent_complete?: number;
  candles?: number;
  idempotency_key?: string;
}

export interface TimingInfo {
  duration_ms: number;
  started_at?: string;
  completed_at?: string;
}

export interface SignalTarget {
  label: string;
  price: number;
  fib_basis?: string;
  close_pct?: number;
  move_stop_to?: string;
}

export interface Signal {
  status: string;
  grade: "A" | "B" | "C" | string;
  direction: "long" | "short" | string;
  pattern_name: string;
  family: string;
  formed: boolean;
  entry_zone: [number, number];
  entry_reference: number;
  stop_loss: number;
  stop_basis?: string;
  targets: SignalTarget[];
  net_rr_tp1?: number;
  net_rr_tp2?: number;
  confluence_score?: number;
  confluence?: Record<string, number>;
  htf_trend?: string;
  invalidation?: number;
  reasoning?: string;
  sharpe?: number;
  regime?: string;
  position_multiplier?: number;
  stability_score?: number;
  trap_score?: number;
}

export interface TechnicalResult {
  pattern_family?: string;
  pattern_type?: string;
  direction?: "bullish" | "bearish" | string;
  entry_price?: number;
  stop_loss?: number;
  target_price?: number;
  risk_reward_ratio?: number;
  confidence?: string;
  divergences?: Record<string, unknown>;
  raw_patterns?: Record<string, unknown>;
  signal?: Signal | null;
  resolved_type?: "formed" | "forming" | null;
}

export interface Interpretation {
  sentiment?: string;
  summary?: string;
  timeframes?: Record<string, unknown>;
  raw_response?: string;
}

export interface AnalysisData {
  analysis_id: string;
  status: AnalysisStatus;
  market: Market;
  symbol: string;
  interval: Interval;
  analysis_type: AnalysisType;
  parameters: Record<string, unknown>;
  technical_result: TechnicalResult;
  interpretation: Interpretation;
  timing: TimingInfo;
}

export interface AnalysisHistoryItem {
  analysis_id: string;
  status: AnalysisStatus;
  market: Market;
  symbol: string;
  interval: Interval;
  analysis_type: AnalysisType;
  direction?: string;
  summary?: string;
  created_at: string;
  duration_ms?: number;
}

/**
 * One field-level error entry returned in `ErrorResponse.details` on a
 * 422 (parseable but semantically rejected) response.
 *
 * Mirrors the backend's :class:`app.domain.schemas.FieldError`:
 *   * `loc` — dot-joined path to the offending field ("interval",
 *     "limit_to", or "" for cross-field / model-level validators).
 *   * `msg` — human-readable explanation.
 *   * `type` — pydantic error type ("literal_error", "greater_than_equal",
 *     "value_error", ...).
 */
export interface FieldError {
  loc: string;
  msg: string;
  type: string;
}

export interface ApiError {
  code: string;
  message: string;
  retryable: boolean;
  request_id?: string;
  /** Mirrors the backend ErrorResponse.details field; populated on 422. */
  details?: FieldError[];
  /** HTTP status code, included so the UI can branch on 4xx vs 5xx. */
  status?: number;
}

export interface ApiSuccess<T> {
  success: true;
  data: T;
}

export interface ApiFailure {
  success: false;
  error: ApiError;
}

export type ApiResponse<T> = ApiSuccess<T> | ApiFailure;

export interface MarketsResponse {
  markets: string[];
  intervals: string[];
  analysis_types: string[];
}
