"use client";

import { useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RsiTrendRequestParams, RsiTrendPlan } from "@/lib/api-rsi-strategy";
import { ParamsForm } from "./params-form";
import { MarketOverviewCard } from "./market-overview-card";
import { TradePlanCard } from "./trade-plan-card";
import { AiInsightCard } from "./ai-insight-card";

interface AnalysisPanelProps {
  result: RsiTrendPlan | null;
  loading: boolean;
  error: string | null;
  onAnalyze: (params: RsiTrendRequestParams) => void;
  className?: string;
}

export function AnalysisPanel({
  result,
  loading,
  error,
  onAnalyze,
  className,
}: AnalysisPanelProps) {
  const [params, setParams] = useState<RsiTrendRequestParams>({
    market: "binance",
    symbol: "BTCUSDT",
    interval: "4h",
    use_ema50: false,
    require_candle_color: false,
    atr_mult: 1.0,
    rsi_zone: "pullback",
    reward_risk: 2.0,
    min_quality_score: 30,
  });

  const update = <K extends keyof RsiTrendRequestParams>(
    key: K,
    value: RsiTrendRequestParams[K]
  ) => setParams((prev) => ({ ...prev, [key]: value }));

  return (
    <section className={cn("glass-card p-5 sm:p-6", className)}>
      <div className="mb-5">
        <h2 className="text-lg font-semibold text-foreground">智能分析</h2>
        <p className="text-sm text-muted-foreground">
          基于 4h K 线分析趋势与动量，生成具体的交易计划、止损目标和仓位建议
        </p>
      </div>

      <ParamsForm
        params={params}
        loading={loading}
        onChange={update}
        intervalHint="（交易计划建议 4h）"
      />

      <button
        type="button"
        onClick={() => onAnalyze(params)}
        disabled={loading || !params.symbol.trim()}
        className="btn-primary mt-5 inline-flex items-center gap-2"
      >
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Sparkles className="h-4 w-4" />
        )}
        {loading ? "分析中..." : "生成交易计划"}
      </button>

      {error && (
        <div className="mt-4 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div className="mt-6 space-y-4 animate-pulse">
          <div className="h-32 w-full rounded-xl bg-muted/50" />
          <div className="h-48 w-full rounded-xl bg-muted/50" />
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <div className="mt-6 space-y-4">
          <MarketOverviewCard overview={result.market_overview} />
          <TradePlanCard plan={result} />
          {result.ai_insight && <AiInsightCard insight={result.ai_insight} />}
          {!result.ai_insight && result.decision.action !== "no_trade" && (
            <p className="text-xs text-muted-foreground text-center">
              AI 解读暂时不可用，规则引擎分析结果仅供参考
            </p>
          )}
        </div>
      )}
    </section>
  );
}
