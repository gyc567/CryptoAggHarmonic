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

export interface RsiTrendRequestParams {
  market?: "binance" | "yahoo";
  symbol: string;
  interval?: "1h" | "4h" | "1d" | "1w";
  use_ema50?: boolean;
  require_candle_color?: boolean;
  /** Float in [0.5, 3.0]. Defaults to 1.0 on the server. */
  atr_mult?: number;
  rsi_zone?: "extreme" | "pullback";
  /** Float in [1.0, 5.0]. Defaults to 2.0 on the server. */
  reward_risk?: number;
  /** Float in [0.0, 100.0]. Defaults to 0 on the server. */
  min_quality_score?: number;
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
  rsi_zone: "extreme" | "pullback";
  reward_risk: number;
  min_quality_score: number;
}

export interface RsiTrendSignal {
  index: number;
  timestamp: string;
  direction: "long" | "short";
  pattern: string;
  grade: string;
  formed: boolean;
  // ... and several numeric fields. Left loose so consumers can read
  // whatever they need; the full schema lives in app.domain.rsi_trend.
  [key: string]: unknown;
}

export interface RsiTrendScanResponse {
  market: string;
  symbol: string;
  interval: string;
  filters: RsiTrendFilters;
  bars: number;
  state: Record<string, unknown>;
  latest_signal: RsiTrendSignal | null;
  recent_signals: RsiTrendSignal[];
}

export interface RsiTrendBacktestResponse extends RsiTrendScanResponse {
  lookback_days: number;
  /**
   * Trade ledger summary produced by run_backtest(...).to_dict().
   * Field set depends on the backtester; kept loose on purpose.
   */
  trades?: unknown[];
  stats?: Record<string, unknown>;
  [key: string]: unknown;
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
