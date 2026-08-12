"use client";

import Link from "next/link";
import type { FtStrategy } from "@/types/ft-strategy";
import { StageProgress } from "./StageProgress";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

interface StrategyCardProps {
  strategy: FtStrategy;
  onDelete?: (id: string) => void;
}

export function StrategyCard({ strategy, onDelete }: StrategyCardProps) {
  const { latest_result: result } = strategy;

  const isRunning = ["hyperopt_running", "backtest_running", "refining"].includes(
    strategy.status
  );

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-4 shadow">
      <div className="mb-2 flex items-start justify-between">
        <div>
          <h3 className="font-semibold text-white">{strategy.name}</h3>
          <p className="text-sm text-gray-400">
            v{strategy.current_version} · {strategy.pair} · {strategy.interval}
          </p>
        </div>
        <span
          className={`
            rounded px-2 py-0.5 text-xs font-medium
            ${strategy.status === "deployed" ? "bg-green-900 text-green-300" : ""}
            ${strategy.status === "rejected" ? "bg-red-900 text-red-300" : ""}
            ${strategy.status === "pending_review" ? "bg-yellow-900 text-yellow-300" : ""}
            ${isRunning ? "bg-blue-900 text-blue-300" : ""}
            ${strategy.status === "draft" ? "bg-gray-700 text-gray-300" : ""}
            ${["analyzed", "refining"].includes(strategy.status) ? "bg-purple-900 text-purple-300" : ""}
          `}
        >
          {strategy.status.replace(/_/g, " ")}
        </span>
      </div>

      <div className="mb-3">
        <StageProgress status={strategy.status} />
      </div>

      {result && (
        <div className="mb-3 grid grid-cols-3 gap-2 rounded bg-gray-900 p-2 text-xs">
          <div>
            <span className="text-gray-400">Win</span>
            <p className="font-mono text-white">
              {result.aggregate.win_rate >= 0
                ? `${(result.aggregate.win_rate * 100).toFixed(1)}%`
                : "—"}
            </p>
          </div>
          <div>
            <span className="text-gray-400">Sharpe</span>
            <p className="font-mono text-white">
              {result.aggregate.sharpe >= -999
                ? result.aggregate.sharpe.toFixed(2)
                : "—"}
            </p>
          </div>
          <div>
            <span className="text-gray-400">DD</span>
            <p className="font-mono text-white">
              {result.aggregate.max_dd >= 0
                ? `${(result.aggregate.max_dd * 100).toFixed(1)}%`
                : "—"}
            </p>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">
          {strategy.last_event
            ? `${strategy.last_event} · ${timeAgo(strategy.updated_at)}`
            : timeAgo(strategy.created_at)}
        </span>
        <div className="flex gap-2">
          <Link
            href={`/ft-strategy/${strategy.id}`}
            className="rounded bg-blue-700 px-3 py-1 text-xs font-medium text-white hover:bg-blue-600"
          >
            查看
          </Link>
          {strategy.status === "analyzed" && (
            <Link
              href={`/ft-strategy/${strategy.id}/backtest`}
              className="rounded bg-purple-700 px-3 py-1 text-xs font-medium text-white hover:bg-purple-600"
            >
              重新回测
            </Link>
          )}
          {onDelete && (
            <button
              onClick={() => onDelete(strategy.id)}
              className="rounded bg-red-900 px-3 py-1 text-xs font-medium text-red-300 hover:bg-red-800"
            >
              删除
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
