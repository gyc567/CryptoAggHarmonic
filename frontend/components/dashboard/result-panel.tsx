"use client";

import { AlertCircle, CheckCircle2, Info, Loader2, TrendingUp, TrendingDown } from "lucide-react";
import { SignalCard } from "@/components/dashboard/signal-card";
import { cn, formatNumber, formatPriceDistance } from "@/lib/utils";
import type { AnalysisData, ApiError } from "@/types";

interface ResultPanelProps {
  result: AnalysisData | null;
  loading: boolean;
  error: ApiError | null;
  className?: string;
}

export function ResultPanel({ result, loading, error, className }: ResultPanelProps) {
  if (loading) {
    return (
      <section className={cn("glass-card p-5 sm:p-6 space-y-4", className)}>
        <div className="flex items-center gap-3 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
          <span className="text-sm font-medium">正在分析，请稍候...</span>
        </div>
        <div className="space-y-3">
          <div className="h-8 w-2/3 shimmer" />
          <div className="h-24 w-full shimmer" />
        </div>
      </section>
    );
  }

  if (error) {
    const hasDetails = Array.isArray(error.details) && error.details.length > 0;
    return (
      <section className={cn("glass-card p-5 sm:p-6", className)}>
        <div className="flex flex-start gap-3 rounded-xl border border-danger/20 bg-danger/10 p-4 text-danger">
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
          <div className="flex-1">
            <p className="font-semibold">分析失败</p>
            <p className="mt-1 text-sm opacity-90">{error.message}</p>
            {hasDetails && (
              <ul className="mt-3 space-y-1 text-sm" data-testid="field-error-list">
                {error.details!.map((d, i) => (
                  <li key={`${d.loc}:${i}`} className="flex items-start gap-2">
                    <span className="rounded bg-danger/20 px-1.5 py-0.5 font-mono text-xs">
                      {d.loc || "(全局)"}
                    </span>
                    <span className="opacity-90">{d.msg}</span>
                  </li>
                ))}
              </ul>
            )}
            {error.request_id && (
              <p className="mt-2 text-xs opacity-70">请求 ID: {error.request_id}</p>
            )}
          </div>
        </div>
      </section>
    );
  }

  if (!result) {
    return (
      <section className={cn("glass-card p-5 sm:p-6", className)}>
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <Info className="h-10 w-10 text-muted-foreground/50" />
          <h3 className="mt-4 text-base font-medium text-foreground">暂无分析结果</h3>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            在上方填写参数并点击&quot;开始分析&quot;，结果将在这里展示
          </p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {["BTCUSDT", "AAPL", "ETHUSDT", "TSLA"].map((symbol) => (
              <span
                key={symbol}
                className="rounded-md bg-elevated px-2 py-1 text-xs text-muted-foreground"
              >
                {symbol}
              </span>
            ))}
          </div>
        </div>
      </section>
    );
  }

  const tech = result.technical_result || {};
  const interp = result.interpretation || {};
  const isBullish = tech.direction?.toLowerCase() === "bullish";
  const isBearish = tech.direction?.toLowerCase() === "bearish";

  // Direction-relative "approaching" semantics:
  //
  //   bullish (long)  : trader wants price to pull DOWN to the PRZ (entry).
  //                     Approaching = current is still ABOVE entry
  //                     (positive % = waiting for the pullback to land).
  //                     Negative % = price has broken below the support,
  //                     the harmonic setup is invalidated.
  //
  //   bearish (short) : trader wants price to rally UP to the PRZ (entry).
  //                     Approaching = current is still BELOW entry
  //                     (negative % = waiting for the rally to land).
  //                     Positive % = price has broken above the resistance,
  //                     the harmonic setup is invalidated.
  //
  // Sign convention of `distanceToEntryPct`:
  //   (current - entry) / entry
  //   positive = current above entry, negative = current below entry.
  const distanceToEntryPct =
    tech.current_price != null && tech.entry_price != null && tech.entry_price > 0
      ? ((tech.current_price - tech.entry_price) / tech.entry_price) * 100
      : null;
  const approachingEntry =
    distanceToEntryPct != null
      ? isBullish
        ? distanceToEntryPct > 0
        : isBearish
          ? distanceToEntryPct < 0
          : false
      : false;

  return (
    <section className={cn("glass-card overflow-hidden", className)}>
      <div className="border-b border-border-subtle bg-elevated/50 px-5 py-4 sm:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={result.status} />
          {(isBullish || isBearish) && (
            <span
              className={cn(
                "badge",
                isBullish ? "badge-success" : "badge-danger"
              )}
            >
              {isBullish ? "看多 Bullish" : "看空 Bearish"}
            </span>
          )}
          {tech.resolved_type && (
            <span className="badge">
              自动 → {tech.resolved_type === "formed" ? "已形成" : "形成中"}
            </span>
          )}
          <span className="ml-auto text-xs text-muted-foreground">
            {result.market.toUpperCase()} · {result.symbol} · {result.interval}
          </span>
        </div>
      </div>

      <div className="space-y-5 p-5 sm:p-6">
        {tech.current_price != null && (
          <div
            className="rounded-xl border border-primary/20 bg-primary/5 p-4"
            data-testid="current-price-card"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <div>
                <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  {approachingEntry ? (
                    <TrendingDown className="h-3.5 w-3.5 text-success" />
                  ) : (
                    <TrendingUp className="h-3.5 w-3.5 text-warning" />
                  )}
                  当前实时价 (Latest close)
                </p>
                <p className="mt-1 font-mono text-2xl font-semibold tabular-nums text-foreground">
                  {formatNumber(tech.current_price)}
                </p>
              </div>
              {tech.entry_price != null && (
                <div className="text-right">
                  <p className="text-xs text-muted-foreground">距入场参考</p>
                  <p
                    className={cn(
                      "mt-0.5 font-mono text-sm font-medium tabular-nums",
                      approachingEntry ? "text-success" : "text-warning"
                    )}
                    data-testid="entry-distance"
                  >
                    {formatPriceDistance(tech.current_price, tech.entry_price)}
                  </p>
                </div>
              )}
            </div>
            {tech.current_price_at && (
              <p className="mt-2 text-[11px] text-muted-foreground/70">
                数据截至 {tech.current_price_at}
              </p>
            )}
          </div>
        )}

        {tech.signal && <SignalCard signal={tech.signal} />}
        <div>
          <h3 className="text-base font-semibold text-foreground">技术结果</h3>
          <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
            <ResultItem label="形态族" value={tech.pattern_family} />
            <ResultItem label="形态类型" value={tech.pattern_type} />
            <ResultItem label="置信度" value={tech.confidence} />
            <ResultItem label="风险收益比" value={formatNumber(tech.risk_reward_ratio ?? undefined)} />
            <ResultItem label="入场价" value={formatNumber(tech.entry_price ?? undefined)} />
            <ResultItem label="止损价" value={formatNumber(tech.stop_loss ?? undefined)} />
            <ResultItem label="目标价" value={formatNumber(tech.target_price ?? undefined)} />
          </dl>
        </div>

        {interp.summary && (
          <div className="rounded-xl border border-border-subtle bg-elevated/50 p-4">
            <h4 className="text-sm font-semibold text-foreground">模型解读</h4>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
              {interp.summary}
            </p>
          </div>
        )}

        <div className="text-xs text-muted-foreground">
          <p>分析 ID: {result.analysis_id}</p>
          {result.timing?.duration_ms ? (
            <p>耗时: {(result.timing.duration_ms / 1000).toFixed(2)}s</p>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function StatusBadge({ status }: { status: string }) {
  const isCompleted = status === "completed";
  return (
    <span
      className={cn(
        "badge",
        isCompleted ? "badge-success" : "badge-warning"
      )}
    >
      {isCompleted ? (
        <CheckCircle2 className="mr-1 h-3 w-3" />
      ) : (
        <Info className="mr-1 h-3 w-3" />
      )}
      {status === "completed"
        ? "已完成"
        : status === "no_result"
        ? "无结果"
        : status}
    </span>
  );
}

function ResultItem({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="rounded-lg bg-elevated px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-medium text-foreground">{value ?? "—"}</dd>
    </div>
  );
}
