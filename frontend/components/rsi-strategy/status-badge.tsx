"use client";

import { TrendingDown, TrendingUp, Minus, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RsiTrendDirection, RsiTrendState } from "@/lib/api-rsi-strategy";

const TREND_CONFIG = {
  bullish: { label: "多头环境", icon: TrendingUp, className: "text-green-500" },
  bearish: { label: "空头环境", icon: TrendingDown, className: "text-red-500" },
  neutral: { label: "趋势不明", icon: Minus, className: "text-muted-foreground" },
} as const;

export function TrendBadge({ trend }: { trend: RsiTrendState["trend"] }) {
  const config = TREND_CONFIG[trend] ?? TREND_CONFIG.neutral;
  const Icon = config.icon;
  return (
    <span className={cn("inline-flex items-center gap-1.5 font-medium", config.className)}>
      <Icon className="h-4 w-4" />
      {config.label}
    </span>
  );
}

export function DirectionBadge({ direction }: { direction: RsiTrendDirection }) {
  const long = direction === "long";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
        long ? "bg-green-500/15 text-green-500" : "bg-red-500/15 text-red-500"
      )}
    >
      {long ? "做多" : "做空"}
    </span>
  );
}

export function EntangledWarning({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-xl border border-yellow-500/30 bg-yellow-500/10 p-3 text-xs text-yellow-600 dark:text-yellow-400",
        className
      )}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      价格在 EMA200 附近缠绕（距离小于 0.5 ATR），属于策略不适用的震荡环境，建议暂停交易。
    </div>
  );
}

const EXIT_REASON_LABELS: Record<string, string> = {
  stop_loss: "止损",
  target: "止盈(1:2)",
  trend_flip: "趋势反转",
  end_of_data: "数据截止",
  partial_target: "减仓(1:2)",
  rsi_extreme: "减仓(RSI极端)",
};

export function ExitReasonBadge({ reason }: { reason: string }) {
  return (
    <span className="text-xs text-muted-foreground">
      {EXIT_REASON_LABELS[reason] ?? reason}
    </span>
  );
}
