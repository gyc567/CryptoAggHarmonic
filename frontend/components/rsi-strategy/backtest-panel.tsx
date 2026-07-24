"use client";

import { useState } from "react";
import { FlaskConical, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  RsiTrendBacktestParams,
  RsiTrendBacktestResponse,
  RsiTrendRequestParams,
} from "@/lib/api-rsi-strategy";
import { ParamsForm } from "./params-form";
import { DirectionBadge, ExitReasonBadge } from "./status-badge";

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  if (value === Infinity) return "∞";
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

interface BacktestPanelProps {
  result: RsiTrendBacktestResponse | null;
  loading: boolean;
  error: string | null;
  onBacktest: (params: RsiTrendBacktestParams) => void;
  className?: string;
}

export function BacktestPanel({ result, loading, error, onBacktest, className }: BacktestPanelProps) {
  const [params, setParams] = useState<RsiTrendBacktestParams>({
    market: "binance",
    symbol: "BTCUSDT",
    interval: "4h",
    use_ema50: false,
    require_candle_color: false,
    atr_mult: 1.0,
    lookback_days: 180,
    partial_mode: false,
  });

  const update = <K extends keyof RsiTrendBacktestParams>(key: K, value: RsiTrendBacktestParams[K]) =>
    setParams((prev) => ({ ...prev, [key]: value }));

  // ParamsForm only manages the shared base params.
  const updateBase = <K extends keyof RsiTrendRequestParams>(
    key: K,
    value: RsiTrendRequestParams[K]
  ) => setParams((prev) => ({ ...prev, [key]: value }));

  return (
    <section className={cn("glass-card p-5 sm:p-6", className)}>
      <div className="mb-5">
        <h2 className="text-lg font-semibold text-foreground">历史回测</h2>
        <p className="text-sm text-muted-foreground">
          用历史数据完整模拟策略的入场、止损、止盈与趋势反转退出，验证有效性
        </p>
      </div>

      <ParamsForm params={params} loading={loading} onChange={updateBase} />

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">
            回溯天数（{params.lookback_days} 天）
          </label>
          <input
            type="range"
            min={60}
            max={365}
            step={30}
            value={params.lookback_days}
            onChange={(e) => update("lookback_days", Number(e.target.value))}
            disabled={loading}
            className="mt-3 w-full accent-primary"
          />
        </div>

        <label className="flex items-center gap-2 text-sm text-foreground">
          <input
            type="checkbox"
            checked={params.partial_mode}
            onChange={(e) => update("partial_mode", e.target.checked)}
            disabled={loading}
            className="h-4 w-4 accent-primary"
          />
          部分止盈模式（1:2 先减 50%，剩余移动止损让利润奔跑）
        </label>
      </div>

      <button
        type="button"
        onClick={() => onBacktest(params)}
        disabled={loading || !params.symbol.trim()}
        className="btn-primary mt-5 inline-flex items-center gap-2"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}
        {loading ? "回测中..." : "开始回测"}
      </button>

      {error && (
        <div className="mt-4 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-6 space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
            <MetricCard label="信号/交易" value={`${result.total_signals}/${result.trades_count}`} />
            <MetricCard
              label="胜率"
              value={`${fmt(result.win_rate * 100, 1)}%`}
              tone={result.win_rate >= 0.5 ? "good" : "bad"}
            />
            <MetricCard
              label="总 R"
              value={fmt(result.total_r)}
              tone={result.total_r > 0 ? "good" : result.total_r < 0 ? "bad" : undefined}
            />
            <MetricCard label="平均 R" value={fmt(result.avg_r)} />
            <MetricCard label="盈亏比 PF" value={fmt(result.profit_factor)} />
            <MetricCard label="最大回撤" value={`${fmt(result.max_drawdown_r)}R`} tone="bad" />
            <MetricCard label="胜/负/平" value={`${result.win_count}/${result.loss_count}/${result.scratch_count}`} />
            <MetricCard label="平均持仓" value={`${fmt(result.avg_bars_held, 1)}根`} />
          </div>

          {result.trades.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              该区间没有产生任何交易信号，可尝试放宽过滤器或更换标的/周期。
            </p>
          ) : (
            <div className="max-h-[28rem] overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b border-border-subtle text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">入场时间</th>
                    <th className="py-2 pr-3 font-medium">方向</th>
                    <th className="py-2 pr-3 font-medium text-right">入场价</th>
                    <th className="py-2 pr-3 font-medium text-right">止损价</th>
                    <th className="py-2 pr-3 font-medium text-right">出场价</th>
                    <th className="py-2 pr-3 font-medium text-right">R 倍数</th>
                    <th className="py-2 pr-3 font-medium">出场原因</th>
                    <th className="py-2 font-medium text-right">持仓</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((t, i) => (
                    <tr key={`${t.entry_time}-${i}`} className="border-b border-border-subtle/50">
                      <td className="py-2 pr-3 text-muted-foreground">{fmtTime(t.entry_time)}</td>
                      <td className="py-2 pr-3"><DirectionBadge direction={t.direction} /></td>
                      <td className="py-2 pr-3 text-right">{fmt(t.entry_price)}</td>
                      <td className="py-2 pr-3 text-right">{fmt(t.stop_loss)}</td>
                      <td className="py-2 pr-3 text-right">{fmt(t.exit_price)}</td>
                      <td
                        className={cn(
                          "py-2 pr-3 text-right font-medium",
                          t.r_multiple > 0
                            ? "text-green-500"
                            : t.r_multiple < 0
                              ? "text-red-500"
                              : "text-muted-foreground"
                        )}
                      >
                        {t.r_multiple > 0 ? "+" : ""}
                        {fmt(t.r_multiple)}R
                      </td>
                      <td className="py-2 pr-3">
                        <ExitReasonBadge reason={t.exit_reason} />
                        {t.partials.length > 0 && (
                          <span className="ml-1 text-xs text-muted-foreground">
                            (+{t.partials.length}次减仓)
                          </span>
                        )}
                      </td>
                      <td className="py-2 text-right text-muted-foreground">{t.bars_held}根</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="text-xs text-muted-foreground">
            历史回测不代表未来收益。建议先用历史数据验证至少 100 个信号，再实盘小仓位验证；严格执行纪律比策略本身更重要。
          </p>
        </div>
      )}
    </section>
  );
}

function MetricCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
}) {
  return (
    <div className="rounded-xl bg-elevated p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div
        className={cn(
          "mt-1 text-sm font-semibold",
          tone === "good" ? "text-green-500" : tone === "bad" ? "text-red-500" : "text-foreground"
        )}
      >
        {value}
      </div>
    </div>
  );
}
