"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  backtestRsiTrend,
  planRsiTrend,
  scanRsiTrend,
  type RsiTrendBacktestParams,
  type RsiTrendBacktestResponse,
  type RsiTrendPlan,
  type RsiTrendRequestParams,
  type RsiTrendScanResponse,
} from "@/lib/api-rsi-strategy";

interface UseRsiStrategyOptions {
  getToken: () => Promise<string | null>;
}

export function useRsiStrategy({ getToken }: UseRsiStrategyOptions) {
  const [scanResult, setScanResult] = useState<RsiTrendScanResponse | null>(null);
  const [scanLoading, setScanLoading] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);

  const [backtestResult, setBacktestResult] = useState<RsiTrendBacktestResponse | null>(null);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestError, setBacktestError] = useState<string | null>(null);

  const [planResult, setPlanResult] = useState<RsiTrendPlan | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);

  const scanAbortRef = useRef<AbortController | null>(null);
  const backtestAbortRef = useRef<AbortController | null>(null);
  const planAbortRef = useRef<AbortController | null>(null);

  const runScan = useCallback(
    async (params: RsiTrendRequestParams) => {
      scanAbortRef.current?.abort();
      const controller = new AbortController();
      scanAbortRef.current = controller;

      setScanLoading(true);
      setScanError(null);
      try {
        const token = await getToken();
        if (!token) { setScanError("未登录"); return; }
        const res = await scanRsiTrend(token, params, controller.signal);
        if (res.success && res.data) setScanResult(res.data);
        else setScanError(typeof res.error === 'string' ? res.error : res.error?.message || "扫描失败");
      } catch (e: unknown) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setScanError(e instanceof Error ? e.message : "扫描失败");
      } finally {
        setScanLoading(false);
      }
    },
    [getToken]
  );

  const runBacktest = useCallback(
    async (params: RsiTrendBacktestParams) => {
      backtestAbortRef.current?.abort();
      const controller = new AbortController();
      backtestAbortRef.current = controller;

      setBacktestLoading(true);
      setBacktestError(null);
      try {
        const token = await getToken();
        if (!token) { setBacktestError("未登录"); return; }
        const res = await backtestRsiTrend(token, params, controller.signal);
        if (res.success && res.data) setBacktestResult(res.data);
        else setBacktestError(typeof res.error === 'string' ? res.error : res.error?.message || "回测失败");
      } catch (e: unknown) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setBacktestError(e instanceof Error ? e.message : "回测失败");
      } finally {
        setBacktestLoading(false);
      }
    },
    [getToken]
  );

  const runPlan = useCallback(
    async (params: RsiTrendRequestParams) => {
      planAbortRef.current?.abort();
      const controller = new AbortController();
      planAbortRef.current = controller;

      setPlanLoading(true);
      setPlanError(null);
      try {
        const token = await getToken();
        if (!token) { setPlanError("未登录"); return; }
        const res = await planRsiTrend(token, params, controller.signal);
        if (res.success && res.data) setPlanResult(res.data);
        else setPlanError(typeof res.error === 'string' ? res.error : res.error?.message || "分析失败");
      } catch (e: unknown) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setPlanError(e instanceof Error ? e.message : "分析失败");
      } finally {
        setPlanLoading(false);
      }
    },
    [getToken]
  );

  // Cancel all on unmount
  useEffect(() => {
    return () => {
      scanAbortRef.current?.abort();
      backtestAbortRef.current?.abort();
      planAbortRef.current?.abort();
    };
  }, []);

  return {
    scanResult, scanLoading, scanError, runScan,
    backtestResult, backtestLoading, backtestError, runBacktest,
    planResult, planLoading, planError, runPlan,
  };
}
