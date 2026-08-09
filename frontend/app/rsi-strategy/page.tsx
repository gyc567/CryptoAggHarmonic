"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { useRsiStrategy } from "@/hooks/use-rsi-strategy";
import { MethodologyCard } from "@/components/rsi-strategy/methodology-card";
import { AnalysisPanel } from "@/components/rsi-strategy/analysis-panel";
import { BacktestPanel } from "@/components/rsi-strategy/backtest-panel";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "plan", label: "智能分析" },
  { key: "backtest", label: "历史回测" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function RsiStrategyPage() {
  const router = useRouter();
  const { user, loading: authLoading, getToken } = useAuth();
  const {
    backtestResult,
    backtestLoading,
    backtestError,
    runBacktest,
    planResult,
    planLoading,
    planError,
    runPlan,
  } = useRsiStrategy({ getToken });
  const [tab, setTab] = useState<TabKey>("plan");

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/auth");
    }
  }, [authLoading, user, router]);

  if (authLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-6 sm:px-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">
          RSI 趋势策略
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          EMA200 定方向，RSI 择时机 —— 顺势交易信号分析
        </p>
      </div>

      <MethodologyCard />

      {/* Tabs */}
      <div className="flex gap-1 rounded-xl bg-muted p-1" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              "flex-1 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
              tab === t.key
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Panels */}
      {tab === "plan" && (
        <AnalysisPanel
          result={planResult}
          loading={planLoading}
          error={planError}
          onAnalyze={runPlan}
        />
      )}
      {tab === "backtest" && (
        <BacktestPanel
          result={backtestResult}
          loading={backtestLoading}
          error={backtestError}
          onBacktest={runBacktest}
        />
      )}
    </div>
  );
}
