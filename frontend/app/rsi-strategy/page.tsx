"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { useRsiStrategy } from "@/hooks/use-rsi-strategy";
import { MethodologyCard } from "@/components/rsi-strategy/methodology-card";
import { ScanPanel } from "@/components/rsi-strategy/scan-panel";
import { BacktestPanel } from "@/components/rsi-strategy/backtest-panel";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "scan", label: "信号扫描" },
  { key: "backtest", label: "历史回测" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function RsiStrategyPage() {
  const router = useRouter();
  const { user, loading: authLoading, getToken } = useAuth();
  const {
    scanResult,
    scanLoading,
    scanError,
    runScan,
    backtestResult,
    backtestLoading,
    backtestError,
    runBacktest,
  } = useRsiStrategy({ getToken });
  const [tab, setTab] = useState<TabKey>("scan");

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace("/login");
    }
  }, [authLoading, user, router]);

  if (authLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <MethodologyCard />

      <div className="flex gap-2 border-b border-border-subtle">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={cn(
              "border-b-2 px-4 py-2 text-sm font-medium transition-colors",
              tab === t.key
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "scan" ? (
        <ScanPanel
          result={scanResult}
          loading={scanLoading}
          error={scanError}
          onScan={runScan}
        />
      ) : (
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
