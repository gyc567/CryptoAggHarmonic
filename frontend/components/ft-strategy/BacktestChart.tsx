"use client";

import type { BacktestResult } from "@/types/ft-strategy";

function MetricBar({
  label,
  value,
  max,
  unit = "",
  goodAbove,
}: {
  label: string;
  value: number;
  max: number;
  unit?: string;
  goodAbove?: number;
}) {
  const pct = max > 0 ? Math.min(100, (Math.abs(value) / max) * 100) : 0;
  const positive = value >= 0;
  const good = goodAbove !== undefined && (goodAbove >= 0 ? value >= goodAbove : value <= -goodAbove);

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-gray-400">{label}</span>
        <span className={`font-mono ${good ? "text-green-400" : "text-red-400"}`}>
          {value >= -999 ? `${positive ? "+" : ""}${value.toFixed(2)}${unit}` : "—"}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded bg-gray-700">
        <div
          className={`h-full transition-all ${good ? "bg-green-600" : "bg-red-600"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

interface BacktestChartProps {
  result: BacktestResult;
  baselineComparison?: {
    drawdown_ok: boolean;
    drawdown_pct: number;
    baseline_drawdown_pct: number;
    calmar_ok: boolean;
    calmar: number;
    baseline_calmar: number;
  };
}

export function BacktestChart({ result, baselineComparison }: BacktestChartProps) {
  const { aggregate, per_pair, per_timerange } = result;

  const maxSharpe = Math.max(...Object.values(per_pair).map((p) => Math.abs(p.sharpe)), 1);
  const maxDD = Math.max(...Object.values(per_pair).map((p) => p.max_dd), 0.01);

  return (
    <div className="space-y-6">
      {/* Aggregate */}
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
        <h3 className="mb-3 text-sm font-semibold text-gray-300">
          📊 Aggregate（v{result.version}）
        </h3>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <MetricBar label="Win Rate" value={aggregate.win_rate * 100} max={100} unit="%" goodAbove={50} />
          <MetricBar label="Sharpe" value={aggregate.sharpe} max={maxSharpe} goodAbove={1} />
          <MetricBar label="Max DD" value={aggregate.max_dd * 100} max={maxDD} unit="%" goodAbove={-10} />
          <MetricBar label="Calmar" value={aggregate.calmar} max={5} goodAbove={1} />
          <MetricBar label="Profit" value={aggregate.profit_pct * 100} max={50} unit="%" goodAbove={0} />
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">Trades</span>
            <span className="font-mono text-white">{aggregate.trades}</span>
          </div>
        </div>

        {baselineComparison && (
          <div className="mt-3 rounded bg-gray-900 p-2">
            <p className="mb-1 text-xs text-gray-400">vs Baseline</p>
            <div className="flex gap-4 text-xs">
              <span className={baselineComparison.drawdown_ok ? "text-green-400" : "text-red-400"}>
                DD {baselineComparison.drawdown_ok ? "✅" : "❌"} ({baselineComparison.drawdown_pct.toFixed(1)}% ≤ {baselineComparison.baseline_drawdown_pct.toFixed(1)}%)
              </span>
              <span className={baselineComparison.calmar_ok ? "text-green-400" : "text-red-400"}>
                Calmar {baselineComparison.calmar_ok ? "✅" : "❌"} ({baselineComparison.calmar.toFixed(2)} ≥ {baselineComparison.baseline_calmar.toFixed(2)})
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Per-Pair */}
      {Object.keys(per_pair).length > 0 && (
        <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-300">Per Pair</h3>
          <div className="space-y-3">
            {Object.entries(per_pair).map(([pair, m]) => (
              <div key={pair} className="space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-gray-300">{pair}</span>
                  <span className="text-gray-400">
                    {m.trades} trades ·{" "}
                    <span className={m.sharpe >= 0 ? "text-green-400" : "text-red-400"}>
                      {m.sharpe >= -999 ? `Sharpe ${m.sharpe.toFixed(2)}` : "—"}
                    </span>
                  </span>
                </div>
                <div className="flex h-2 gap-0.5">
                  <div
                    className="h-full bg-blue-600"
                    style={{ width: `${Math.min(100, Math.abs(m.sharpe) / maxSharpe * 100)}%` }}
                    title={`Sharpe ${m.sharpe.toFixed(2)}`}
                  />
                  <div
                    className="h-full bg-red-600"
                    style={{ width: `${Math.min(100, m.max_dd / maxDD * 100)}%` }}
                    title={`DD ${(m.max_dd * 100).toFixed(1)}%`}
                  />
                </div>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-gray-500">Blue = Sharpe · Red = Max Drawdown</p>
        </div>
      )}

      {/* Per-Timerange */}
      {Object.keys(per_timerange).length > 0 && (
        <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-300">Per Timerange</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-400">
                  <th className="text-left">Range</th>
                  <th className="text-right">Sharpe</th>
                  <th className="text-right">Max DD</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(per_timerange).map(([range, m]) => (
                  <tr key={range} className="border-t border-gray-700">
                    <td className="py-1 text-gray-300">{range}</td>
                    <td className={`text-right font-mono ${m.sharpe >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {m.sharpe >= -999 ? m.sharpe.toFixed(2) : "—"}
                    </td>
                    <td className="text-right font-mono text-red-400">
                      {m.max_dd >= 0 ? `${(m.max_dd * 100).toFixed(1)}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
