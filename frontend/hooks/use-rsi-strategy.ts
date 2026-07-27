"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  backtestRsiTrend,
  scanRsiTrend,
  type RsiTrendBacktestParams,
  type RsiTrendBacktestResponse,
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

  const scanAbortRef = useRef<AbortController | null>(null);
  const backtestAbortRef = useRef<AbortController | null>(null);

  const runScan = useCallback(
    async (params: RsiTrendRequestParams) => {
      // Cancel any pending scan before starting a new one.
      scanAbortRef.current?.abort();
      const controller = new AbortController();
      scanAbortRef.current = controller;

      setScanLoading(true);
      setScanError(null);
      try {
        const token = await getToken();
        if (!token) {
          setScanError("未登录或会话已过期");
          return;
        }
        const res = await scanRsiTrend(token, params, controller.signal);
        if (controller.signal.aborted) return;
        if (res.success) {
          setScanResult(res.data);
        } else {
          setScanError(res.error.message);
          setScanResult(null);
        }
      } finally {
        if (!controller.signal.aborted) {
          setScanLoading(false);
        }
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
        if (!token) {
          setBacktestError("未登录或会话已过期");
          return;
        }
        const res = await backtestRsiTrend(token, params, controller.signal);
        if (controller.signal.aborted) return;
        if (res.success) {
          setBacktestResult(res.data);
        } else {
          setBacktestError(res.error.message);
          setBacktestResult(null);
        }
      } finally {
        if (!controller.signal.aborted) {
          setBacktestLoading(false);
        }
      }
    },
    [getToken]
  );

  // Abort pending requests when the component/hook unmounts.
  useEffect(() => {
    return () => {
      scanAbortRef.current?.abort();
      backtestAbortRef.current?.abort();
    };
  }, []);

  return {
    scanResult,
    scanLoading,
    scanError,
    runScan,
    backtestResult,
    backtestLoading,
    backtestError,
    runBacktest,
  };
}
