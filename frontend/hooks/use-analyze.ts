"use client";

import { useState, useCallback, useEffect } from "react";
import { analyze, appendLocalHistory, getMarkets } from "@/lib/api";
import { getSymbols } from "@/lib/symbols";
import { generateIdempotencyKey } from "@/lib/utils";
import type {
  AnalysisData,
  AnalyzeRequest,
  AnalysisHistoryItem,
  ApiError,
  MarketsResponse,
} from "@/types";

const DEFAULT_MARKET =
  (process.env.NEXT_PUBLIC_DEFAULT_MARKET as AnalyzeRequest["market"]) || "binance";

const DEFAULT_FORM: AnalyzeRequest = {
  market: DEFAULT_MARKET,
  symbol: "",
  // Default to 4h for crypto (matches the dashboard URL `/dashboard` so a fresh
  // page load opens with the same period the URL deep-link implies). Yahoo
  // defaults stay at 1d because sub-daily candles are not always available for
  // every ticker on the legacy Yahoo adapter.
  interval: DEFAULT_MARKET === "yahoo" ? "1d" : "4h",
  analysis_type: "auto",
  limit_to: 10,
  percent_complete: 0.8,
  candles: 1000,
};

function buildInitialForm(): AnalyzeRequest {
  const market = DEFAULT_FORM.market;
  const symbols = getSymbols(market);
  return { ...DEFAULT_FORM, symbol: symbols[0] ?? "" };
}

export function useAnalyze(getToken: () => Promise<string | null>) {
  const [form, setForm] = useState<AnalyzeRequest>(buildInitialForm);
  const [markets, setMarkets] = useState<MarketsResponse | null>(null);
  const [symbols, setSymbols] = useState<string[]>(() => getSymbols(form.market));
  const [result, setResult] = useState<AnalysisData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const updateField = useCallback(
    <K extends keyof AnalyzeRequest>(key: K, value: AnalyzeRequest[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
    },
    []
  );

  const loadMarkets = useCallback(async () => {
    const token = await getToken();
    if (!token) return;
    const res = await getMarkets(token, { retry: 2, retryDelayMs: 300 });
    // The backend may return either a wrapped ApiResponse or a plain MarketsResponse.
    const next: MarketsResponse | null =
      "data" in res ? res.data : "markets" in res ? (res as unknown as MarketsResponse) : null;
    if (next) {
      setMarkets(next);
    }
  }, [getToken]);

  useEffect(() => {
    const list = getSymbols(form.market);
    setSymbols(list);
    setForm((prev) => ({
      ...prev,
      symbol: list.includes(prev.symbol) ? prev.symbol : list[0] ?? "",
    }));
  }, [form.market]);

  const submit = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);

    const token = await getToken();
    if (!token) {
      setLoading(false);
      setError({
        code: "UNAUTHORIZED",
        message: "请先登录",
        retryable: false,
      });
      return;
    }

    const payload: AnalyzeRequest = {
      ...form,
      symbol: form.symbol.trim().toUpperCase(),
      idempotency_key: generateIdempotencyKey(),
    };

    const res = await analyze(token, payload, { retry: 2, retryDelayMs: 500 });
    setLoading(false);

    if ("error" in res) {
      setError(res.error);
      return;
    }

    setResult(res.data);

    const historyItem: AnalysisHistoryItem = {
      analysis_id: res.data.analysis_id,
      status: res.data.status,
      market: res.data.market,
      symbol: res.data.symbol,
      interval: res.data.interval,
      analysis_type: res.data.analysis_type,
      direction: res.data.technical_result?.direction,
      summary: res.data.interpretation?.summary,
      created_at: new Date().toISOString(),
      duration_ms: res.data.timing?.duration_ms,
    };
    appendLocalHistory(historyItem);
  }, [form, getToken]);

  const reset = useCallback(() => {
    setResult(null);
    setError(null);
  }, []);

  return {
    form,
    markets,
    symbols,
    result,
    loading,
    error,
    updateField,
    loadMarkets,
    submit,
    reset,
  };
}
