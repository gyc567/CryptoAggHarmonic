"use client";

import { useCallback, useState } from "react";
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

  const runScan = useCallback(
    async (params: RsiTrendRequestParams) => {
      setScanLoading(true);
      setScanError(null);
      try {
        const token = await getToken();
        if (!token) {
          setScanError("未登录或会话已过期");
          return;
        }
        const res = await scanRsiTrend(token, params);
        if (res.success) {
          setScanResult(res.data);
        } else {
          setScanError(res.error.message);
          setScanResult(null);
        }
      } finally {
        setScanLoading(false);
      }
    },
    [getToken]
  );

  const runBacktest = useCallback(
    async (params: RsiTrendBacktestParams) => {
      setBacktestLoading(true);
      setBacktestError(null);
      try {
        const token = await getToken();
        if (!token) {
          setBacktestError("未登录或会话已过期");
          return;
        }
        const res = await backtestRsiTrend(token, params);
        if (res.success) {
          setBacktestResult(res.data);
        } else {
          setBacktestError(res.error.message);
          setBacktestResult(null);
        }
      } finally {
        setBacktestLoading(false);
      }
    },
    [getToken]
  );

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
