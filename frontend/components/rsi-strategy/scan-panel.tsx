"use client";

import { useState } from "react";
import { Loader2, Radar } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  RsiTrendRequestParams,
  RsiTrendScanResponse,
} from "@/lib/api-rsi-strategy";
import { ParamsForm } from "./params-form";
import { DirectionBadge, EntangledWarning, TrendBadge } from "./status-badge";

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtTime(iso: string): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

interface ScanPanelProps {
  result: RsiTrendScanResponse | null;
  loading: boolean;
  error: string | null;
  onScan: (params: RsiTrendRequestParams) => void;
  className?: string;
}

export function ScanPanel({ result, loading, error, onScan, className }: ScanPanelProps) {
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

  const update = <K extends keyof RsiTrendRequestParams>(key: K, value: RsiTrendRequestParams[K]) =>
    setParams((prev) => ({ ...prev, [key]: value }));

  const state = result?.state;

  return (
    <section className={cn("glass-card p-5 sm:p-6", className)}>
      <div className="mb-5">
        <h2 className="text-lg font-semibold text-foreground">信号扫描</h2>
        <p className="text-sm text-muted-foreground">
          检查当前趋势环境与 RSI 动量，寻找「离开极端/回调区域」的顺势入场信号
        </p>
      </div>

      <ParamsForm params={params} loading={loading} onChange={update} />

      <button
        type="button"
        onClick={() => onScan(params)}
        disabled={loading || !params.symbol.trim()}
        className="btn-primary mt-5 inline-flex items-center gap-2"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Radar className="h-4 w-4" />}
        {loading ? "扫描中..." : "开始扫描"}
      </button>

      {error && (
        <div className="mt-4 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {result && state && (
        <div className="mt-6 space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard label="趋势环境" value={<TrendBadge trend={state.trend} />} />
            <StatCard
              label="EMA200 偏离"
              value={`${state.deviation_pct >= 0 ? "+" : ""}${fmt(state.deviation_pct)}%`}
            />
            <StatCard label="RSI(14)" value={fmt(state.rsi, 1)} />
            <StatCard label="收盘价" value={fmt(state.close)} />
            <StatCard label="EMA200" value={fmt(state.ema200)} />
            <StatCard label="EMA50" value={fmt(state.ema50)} />
          </div>

          {state.entangled && <EntangledWarning />}

          {result.latest_signal ? (
            <div
              className={cn(
                "rounded-xl border p-4",
                result.latest_signal.direction === "long"
                  ? "border-green-500/30 bg-green-500/5"
                  : "border-red-500/30 bg-red-500/5"
              )}
            >
              <div className="flex flex-wrap items-center gap-3">
                <DirectionBadge direction={result.latest_signal.direction} />
                <span className="text-sm font-medium text-foreground">最新信号</span>
                <span className="text-xs text-muted-foreground">
                  {fmtTime(result.latest_signal.time)}
                </span>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
                <StatCard label="入场价（信号K线收盘）" value={fmt(result.latest_signal.entry_price)} compact />
                <StatCard label="止损价" value={fmt(result.latest_signal.stop_loss)} compact />
                <StatCard label={`目标价 (1:${result.filters.reward_risk.toFixed(1)})`} value={fmt(result.latest_signal.target_price)} compact />
                <StatCard label="信号时 RSI" value={fmt(result.latest_signal.rsi, 1)} compact />
                <StatCard label="质量分" value={`${Math.round(result.latest_signal.quality_score)}`} compact />
              </div>
              <p className="mt-3 text-xs text-muted-foreground">
                建议单笔风险控制在总资金的 0.5%–1%，仓位 = 可承受亏损 ÷（入场价 − 止损价）。
              </p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              最近 500 根K线内没有符合过滤条件的信号。
            </p>
          )}

          {result.recent_signals.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-subtle text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">时间</th>
                    <th className="py-2 pr-3 font-medium">方向</th>
                    <th className="py-2 pr-3 font-medium text-right">入场价</th>
                    <th className="py-2 pr-3 font-medium text-right">止损价</th>
                    <th className="py-2 pr-3 font-medium text-right">目标价</th>
                    <th className="py-2 pr-3 font-medium text-right">RSI</th>
                    <th className="py-2 font-medium text-right">质量分</th>
                  </tr>
                </thead>
                <tbody>
                  {result.recent_signals.map((s) => (
                    <tr key={`${s.index}-${s.direction}`} className="border-b border-border-subtle/50">
                      <td className="py-2 pr-3 text-muted-foreground">{fmtTime(s.time)}</td>
                      <td className="py-2 pr-3"><DirectionBadge direction={s.direction} /></td>
                      <td className="py-2 pr-3 text-right">{fmt(s.entry_price)}</td>
                      <td className="py-2 pr-3 text-right">{fmt(s.stop_loss)}</td>
                      <td className="py-2 pr-3 text-right">{fmt(s.target_price)}</td>
                      <td className="py-2 pr-3 text-right">{fmt(s.rsi, 1)}</td>
                      <td className="py-2 text-right">{Math.round(s.quality_score)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
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
