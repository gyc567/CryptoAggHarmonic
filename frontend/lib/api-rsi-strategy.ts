/**
 * API wrapper for the trend-RSI strategy endpoints.
 *
 * Backend: app/api/rsi_trend_routes.py
 *   GET  /api/rsi-trend/scan      (auth required, query params)
 *   POST /api/rsi-trend/backtest  (auth required, JSON body)
 *
 * Schema source of truth: app/domain/rsi_trend_schemas.py.
 *
 * This file was missing from the original commit
 * ``feat: 趋势RSI策略模块（EMA200过滤+RSI择时）及既有改动`` that introduced
 * ``hooks/use-rsi-strategy.ts`` — the hook imported a non-existent module,
 * which surfaced as a Next.js dev compile error and broke ``/``.
 */

import { request } from "@/lib/api";
import type { ApiResponse } from "@/types";

// --- Request types ----------------------------------------------------------

export type RsiTrendMarket = "binance" | "yahoo";
export type RsiTrendInterval = "1h" | "4h" | "1d" | "1w";
export type RsiTrendZone = "extreme" | "pullback";

export interface RsiTrendRequestParams {
  market: RsiTrendMarket;
  symbol: string;
  interval: RsiTrendInterval;
  use_ema50: boolean;
  require_candle_color: boolean;
  /** Float in [0.5, 3.0]. Defaults to 1.0 on the server. */
  atr_mult: number;
  rsi_zone: RsiTrendZone;
  /** Float in [1.0, 5.0]. Defaults to 2.0 on the server. */
  reward_risk: number;
  /** Float in [0.0, 100.0]. Defaults to 0 on the server. */
  min_quality_score: number;
}

export interface RsiTrendBacktestParams extends RsiTrendRequestParams {
  /** Int in [60, 365]. Defaults to 180 on the server. */
  lookback_days?: number;
  partial_mode?: boolean;
  trailing_stop?: boolean;
}

// --- Response types ---------------------------------------------------------
//
// The backend returns a free-form dict (see app.services.rsi_trend_service).
// We type the known top-level shape and leave the trade-ledger details
// loose so internal additions don't force a TS rebuild.

export interface RsiTrendFilters {
  use_ema50: boolean;
  require_candle_color: boolean;
  atr_mult: number;
  rsi_zone: RsiTrendZone;
  reward_risk: number;
  min_quality_score: number;
}

export type RsiTrendDirection = "long" | "short";

/** Latest trend/momentum snapshot — mirrors app.domain.rsi_trend.current_state(). */
export interface RsiTrendState {
  time: string;
  close: number;
  ema200: number;
  ema50: number;
  rsi: number | null;
  atr: number | null;
  trend: "bullish" | "bearish" | "neutral";
  deviation_pct: number;
  entangled: boolean;
}

/** Mirrors app.domain.rsi_trend.StrategySignal.to_dict(). */
export interface RsiTrendSignal {
  direction: RsiTrendDirection;
  entry_price: number;
  stop_loss: number;
  target_price: number;
  atr: number;
  rsi: number;
  /** ISO timestamp of the signal bar ("" if unavailable). */
  time: string;
  /** Positional bar index within the analysed DataFrame. */
  index: number;
  quality_score: number;
}

export interface RsiTrendScanResponse {
  market: string;
  symbol: string;
  interval: string;
  filters: RsiTrendFilters;
  bars: number;
  state: RsiTrendState | null;
  latest_signal: RsiTrendSignal | null;
  recent_signals: RsiTrendSignal[];
}

export interface RsiTrendBacktestTrade {
  direction: "long" | "short";
  entry_price: number;
  entry_time: string;
  stop_loss: number;
  target_price: number;
  exit_price: number;
  exit_time: string;
  exit_reason: string;
  r_multiple: number;
  bars_held: number;
  partials: { fraction: number; price: number; r_multiple: number; reason: string; time: string }[];
}

export interface RsiTrendBacktestResponse extends RsiTrendScanResponse {
  lookback_days: number;
  filters: RsiTrendFilters & { partial_mode: boolean; trailing_stop: boolean };
  bars: number;
  total_signals: number;
  trades_count: number;
  win_count: number;
  loss_count: number;
  scratch_count: number;
  win_rate: number;
  avg_r: number;
  total_r: number;
  profit_factor: number | null;
  max_drawdown_r: number;
  avg_bars_held: number;
  trades: RsiTrendBacktestTrade[];
}

// --- Helpers ---------------------------------------------------------------

function toQuery(params: RsiTrendRequestParams): string {
  const usp = new URLSearchParams();
  if (params.market !== undefined) usp.set("market", params.market);
  if (params.symbol) usp.set("symbol", params.symbol);
  if (params.interval) usp.set("interval", params.interval);
  if (params.use_ema50 !== undefined) usp.set("use_ema50", String(params.use_ema50));
  if (params.require_candle_color !== undefined) {
    usp.set("require_candle_color", String(params.require_candle_color));
  }
  if (params.atr_mult !== undefined) usp.set("atr_mult", String(params.atr_mult));
  if (params.rsi_zone) usp.set("rsi_zone", params.rsi_zone);
  if (params.reward_risk !== undefined) usp.set("reward_risk", String(params.reward_risk));
  if (params.min_quality_score !== undefined) {
    usp.set("min_quality_score", String(params.min_quality_score));
  }
  return usp.toString();
}

// --- Public functions ------------------------------------------------------

export function scanRsiTrend(
  token: string | null,
  params: RsiTrendRequestParams,
  signal?: AbortSignal
): Promise<ApiResponse<RsiTrendScanResponse>> {
  return request<RsiTrendScanResponse>(
    `/api/rsi-trend/scan?${toQuery(params)}`,
    token,
    signal ? { signal } : undefined
  );
}

export function backtestRsiTrend(
  token: string | null,
  params: RsiTrendBacktestParams,
  signal?: AbortSignal
): Promise<ApiResponse<RsiTrendBacktestResponse>> {
  return request<RsiTrendBacktestResponse>("/api/rsi-trend/backtest", token, {
    method: "POST",
    body: JSON.stringify(params),
    ...(signal ? { signal } : {}),
  });
}

// --- Trading Plan types ------------------------------------------------------

export interface RsiTrendPlanEntry {
  price: number;
  trigger: string;
  entry_type: string;
}

export interface RsiTrendPlanStop {
  price: number;
  logic: string;
  distance_atr: number;
}

export interface RsiTrendPlanTarget {
  level: string;
  price: number;
  rr: number;
  weight: number;
}

export interface RsiTrendPlanPosition {
  risk_per_trade_pct: number | null;
  total_capital_wu: number | null;
  risk_amount_wu: number | null;
  position_size_wu: number | null;
  position_size_u: number | null;
  sizing_note: string;
  configured: boolean;
}

export interface RsiTrendPlanManagement {
  breakeven_after: string;
  trailing_stop: boolean;
  time_stop: string;
}

export interface RsiTrendPlanDecision {
  action: "trade" | "watch" | "no_trade";
  direction: "long" | "short" | null;
  confidence: number;
  reasons: string[];
  warnings: string[];
  watch_for?: string;
}

export interface RsiTrendPlanMarketOverview {
  trend: "bullish" | "bearish" | "neutral";
  trend_strength: number;
  close: number;
  ema200: number;
  ema50: number;
  deviation_pct: number;
  rsi: number | null;
  atr: number | null;
  atr_pct: number | null;
  volatility_regime: string;
  entangled: boolean;
  notes: string[];
}

export interface RsiTrendPlan {
  symbol: string;
  interval: string;
  generated_at: string;
  plan_non_prod: boolean;
  market_overview: RsiTrendPlanMarketOverview;
  decision: RsiTrendPlanDecision;
  plan?: {
    entry: RsiTrendPlanEntry;
    stop: RsiTrendPlanStop;
    targets: RsiTrendPlanTarget[];
    risk_reward: number;
    position: RsiTrendPlanPosition;
    management: RsiTrendPlanManagement;
  } | null;
  multi_tf: unknown;
  invalidation: string[];
  history?: {
    signals_count: number;
    longs?: number;
    shorts?: number;
    avg_quality?: number;
    note: string;
  } | null;
  ai_insight?: {
    summary: string;
    risk_note: string;
    disclaimer: string;
    cached: boolean;
  } | null;
}

// --- Plan API ----------------------------------------------------------------

export function planRsiTrend(
  token: string | null,
  params: RsiTrendRequestParams,
  signal?: AbortSignal
): Promise<ApiResponse<RsiTrendPlan>> {
  return request<RsiTrendPlan>(
    `/api/rsi-trend/plan?${toQuery(params)}`,
    token,
    signal ? { headers: { Authorization: `Bearer ${token}` }, signal } : undefined
  );
}
