"use client";

import { cn } from "@/lib/utils";
import type { RsiTrendPlan } from "@/lib/api-rsi-strategy";
import { DirectionBadge } from "./status-badge";

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

interface Props {
  plan: RsiTrendPlan;
  className?: string;
}

export function TradePlanCard({ plan, className }: Props) {
  const { decision, plan: planData } = plan;

  return (
    <section className={cn("glass-card p-5 sm:p-6", className)}>
      {/* Decision header */}
      <div
        className={cn(
          "mb-4 flex items-center gap-3 rounded-xl border p-4",
          decision.action === "trade"
            ? decision.direction === "long"
              ? "border-green-500/30 bg-green-500/5"
              : "border-red-500/30 bg-red-500/5"
            : decision.action === "watch"
            ? "border-amber-500/30 bg-amber-500/5"
            : "border-muted-foreground/30 bg-muted/10"
        )}
      >
        {decision.direction && <DirectionBadge direction={decision.direction} />}
        <div className="flex-1">
          <span className="text-sm font-semibold text-foreground">
            {decision.action === "trade"
              ? "交易信号"
              : decision.action === "watch"
              ? "观望等待"
              : "暂无信号"}
          </span>
          {decision.action === "trade" && (
            <span className="ml-2 text-xs text-muted-foreground">
              置信度 {(decision.confidence * 100).toFixed(0)}%
            </span>
          )}
        </div>
      </div>

      {/* Reasons & warnings */}
      {decision.reasons.length > 0 && (
        <ul className="mb-3 space-y-1">
          {decision.reasons.map((r, i) => (
            <li key={i} className="text-xs text-muted-foreground">
              ✓ {r}
            </li>
          ))}
        </ul>
      )}
      {decision.warnings.length > 0 && (
        <ul className="mb-3 space-y-1">
          {decision.warnings.map((w, i) => (
            <li key={i} className="text-xs text-amber-600 dark:text-amber-400">
              ⚠ {w}
            </li>
          ))}
        </ul>
      )}

      {/* Watch-for hint */}
      {decision.action === "watch" && decision.watch_for && (
        <p className="mb-3 text-sm text-muted-foreground">
          📡 {decision.watch_for}
        </p>
      )}

      {/* Trade plan details */}
      {decision.action === "trade" && planData && (
        <div className="space-y-4">
          {/* Entry / Stop / Targets */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <MiniStat label="入场价" value={fmt(planData.entry.price)} />
            <MiniStat label="止损价" value={fmt(planData.stop.price)} />
            {planData.targets.map((t) => (
              <MiniStat
                key={t.level}
                label={t.level.toUpperCase()}
                value={`${fmt(t.price)} (${t.rr}R)`}
              />
            ))}
          </div>

          {/* Position */}
          {planData.position.configured && (
            <div className="rounded-xl bg-elevated p-3">
              <p className="text-xs text-muted-foreground">
                建议仓位：{fmt(planData.position.position_size_u, 2)} U
                {planData.position.sizing_note && (
                  <span className="ml-2 italic">{planData.position.sizing_note}</span>
                )}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                单笔风险：{fmt(planData.position.risk_per_trade_pct)}% ×{" "}
                {fmt(planData.position.total_capital_wu)} WU ={" "}
                {fmt(planData.position.risk_amount_wu)} WU
              </p>
            </div>
          )}
          {!planData.position.configured && (
            <div className="rounded-xl bg-muted/50 p-3 text-xs text-muted-foreground">
              未设置账户资金 →{" "}
              <a href="/position" className="underline underline-offset-2">
                前往仓位管理页面
              </a>{" "}
              设置后自动计算仓位
            </div>
          )}

          {/* Management */}
          <div className="text-xs text-muted-foreground space-y-1">
            <p>
              📋 止盈管理：到 TP1 后移损至保本
              {planData.management.trailing_stop && " + 跟踪止损"}
            </p>
            <p>⏱ {planData.management.time_stop}</p>
          </div>
        </div>
      )}

      {/* Invalidation (collapsible, always shown) */}
      {plan.invalidation.length > 0 && (
        <details className="mt-4 text-xs text-muted-foreground">
          <summary className="cursor-pointer font-medium text-muted-foreground">
            失效条件
          </summary>
          <ul className="mt-2 space-y-1">
            {plan.invalidation.map((inv, i) => (
              <li key={i}>✕ {inv}</li>
            ))}
          </ul>
        </details>
      )}

      {/* History reference */}
      {plan.history && (plan.history.signals_count as number) > 0 && (
        <div className="mt-4 rounded-xl bg-muted/30 p-3">
          <p className="text-xs text-muted-foreground">
            📊 近端参考：{String(plan.history.signals_count)} 个历史信号
            {plan.history.note && (
              <span className="ml-1 italic">— {String(plan.history.note)}</span>
            )}
          </p>
        </div>
      )}
    </section>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-elevated p-2.5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-1 text-sm font-semibold text-foreground">{value}</div>
    </div>
  );
}
