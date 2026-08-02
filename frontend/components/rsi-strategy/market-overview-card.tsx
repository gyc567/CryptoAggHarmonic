"use client";

import { cn } from "@/lib/utils";
import type { RsiTrendPlanMarketOverview } from "@/lib/api-rsi-strategy";
import { TrendBadge, EntangledWarning } from "./status-badge";

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

interface Props {
  overview: RsiTrendPlanMarketOverview;
  className?: string;
}

export function MarketOverviewCard({ overview, className }: Props) {
  return (
    <section className={cn("glass-card p-5 sm:p-6", className)}>
      <h2 className="mb-4 text-lg font-semibold text-foreground">市场概况</h2>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="趋势环境" value={<TrendBadge trend={overview.trend} />} />
        <StatCard
          label="趋势强度"
          value={`${(overview.trend_strength * 100).toFixed(0)}%`}
        />
        <StatCard label="RSI(14)" value={fmt(overview.rsi, 1)} />
        <StatCard label="收盘价" value={fmt(overview.close)} />
        <StatCard
          label="EMA200 偏离"
          value={`${overview.deviation_pct >= 0 ? "+" : ""}${fmt(overview.deviation_pct)}%`}
        />
        <StatCard label="波动率" value={overview.volatility_regime} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
        <span className="text-muted-foreground">
          EMA200: {fmt(overview.ema200)}
        </span>
        <span className="text-muted-foreground">
          EMA50: {fmt(overview.ema50)}
        </span>
        <span className="text-muted-foreground">
          ATR: {fmt(overview.atr)}
        </span>
        <span className="text-muted-foreground">
          ATR%: {fmt(overview.atr_pct)}%
        </span>
      </div>

      {overview.entangled && <EntangledWarning className="mt-3" />}

      {overview.notes.length > 0 && (
        <ul className="mt-3 space-y-1">
          {overview.notes.map((note, i) => (
            <li key={i} className="text-xs text-muted-foreground">
              • {note}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function StatCard({
  label,
  value,
  compact,
}: {
  label: string;
  value: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={cn("rounded-xl bg-elevated", compact ? "p-2.5" : "p-3")}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-1 text-sm font-semibold text-foreground">{value}</div>
    </div>
  );
}
