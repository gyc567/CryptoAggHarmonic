"use client";

import { useEffect, useState, useCallback, use } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { StageProgress } from "@/components/ft-strategy/StageProgress";
import { HyperoptProgress } from "@/components/ft-strategy/HyperoptProgress";
import {
  getStrategy,
  getStrategyOrient,
  getJobs,
  refineStrategy,
  deployStrategy,
} from "@/lib/api-ft-strategy";
import type {
  FtStrategy,
  FtStrategyRun,
  OrientEntry,
  BacktestResult,
} from "@/types/ft-strategy";

const RUNNING_STATUSES = new Set(["queued", "running"]);

export default function FtStrategyDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const { user, getToken } = useAuth();

  const [strategy, setStrategy] = useState<FtStrategy | null>(null);
  const [orient, setOrient] = useState<OrientEntry | null>(null);
  const [runs, setRuns] = useState<FtStrategyRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [refining, setRefining] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isRunning =
    strategy?.status === "hyperopt_running" ||
    strategy?.status === "backtest_running" ||
    strategy?.status === "refining";

  const activeRun = runs.find((r) => RUNNING_STATUSES.has(r.status));

  const load = useCallback(async () => {
    if (!user) return;
    const token = await getToken();
    if (!token) return;
    try {
      const [s, o, j] = await Promise.all([
        getStrategy(id, token),
        getStrategyOrient(id, token),
        getJobs(id, token),
      ]);
      setStrategy(s);
      setOrient(o);
      setRuns(j);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [user, getToken, id]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll: 10s when running, 30s otherwise
  useEffect(() => {
    const interval = setInterval(load, isRunning ? 10000 : 30000);
    return () => clearInterval(interval);
  }, [load, isRunning]);

  async function handleRefine() {
    if (!user || !strategy) return;
    setRefining(true);
    try {
      const token = await getToken();
      if (!token) return;
      await refineStrategy(strategy.id, { params_delta: {} }, token);
      router.push(`/ft-strategy/${strategy.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRefining(false);
    }
  }

  async function handleDeploy() {
    if (!user || !strategy) return;
    setDeploying(true);
    try {
      const token = await getToken();
      if (!token) return;
      await deployStrategy(strategy.id, token);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDeploying(false);
    }
  }

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    );
  }

  if (!strategy) {
    return (
      <div className="p-6 text-center text-gray-400">
        <p>策略不存在或无权限访问。</p>
        <Link href="/ft-strategy" className="mt-2 text-blue-400 hover:underline">
          ← 返回列表
        </Link>
      </div>
    );
  }

  const latestResult = strategy.latest_result as BacktestResult | undefined;

  return (
    <div className="p-4 sm:p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <Link
              href="/ft-strategy"
              className="mb-2 text-sm text-gray-400 hover:text-white"
            >
              ← FT 策略
            </Link>
            <h1 className="text-xl font-bold text-white">{strategy.name}</h1>
            <p className="text-sm text-gray-400">
              v{strategy.current_version} · {strategy.pair} · {strategy.interval}
              {strategy.stagnation_count >= 3 && (
                <span className="ml-2 rounded bg-yellow-900 px-1.5 py-0.5 text-xs text-yellow-300">
                  ⚠️ stagnation {strategy.stagnation_count}≥3
                </span>
              )}
            </p>
          </div>
          <div className="flex gap-2">
            {strategy.status === "analyzed" && (
              <button
                onClick={handleRefine}
                disabled={refining}
                className={`rounded bg-purple-700 px-3 py-1.5 text-sm font-medium text-white ${
                  refining ? "opacity-50" : "hover:bg-purple-600"
                }`}
              >
                {refining ? "提交中..." : "🔄 重新回测"}
              </button>
            )}
          </div>
        </div>

        {/* Orient Banner */}
        {orient && orient.next_action.type !== "none" && (
          <div className="rounded border border-blue-800 bg-blue-950/40 p-3 text-sm">
            <p className="font-medium text-blue-300">
              {orient.next_action.type === "wait_backtest"
                ? "⏳ 等待回测"
                : orient.next_action.type === "refine"
                ? "🔄 建议优化"
                : orient.next_action.type === "apply_deploy_pr"
                ? "🚀 可以部署"
                : "⏳ 完成 shadow"}{" "}
              — {orient.next_action.reason}
            </p>
            {orient.hard_blockers.length > 0 && (
              <p className="mt-1 text-xs text-red-400">
                障碍：{orient.hard_blockers.join(" · ")}
              </p>
            )}
          </div>
        )}

        {/* Stage Progress */}
        <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
          <StageProgress status={strategy.status} />
        </div>

        {/* Active Run Progress */}
        {isRunning && activeRun && (
          <HyperoptProgress
            progressPct={activeRun.progress_pct}
            candidates={
              typeof activeRun.result === "object"
                ? (activeRun.result as {candidates_evaluated?: number})?.candidates_evaluated
                : undefined
            }
            bestProfit={
              typeof activeRun.result === "object"
                ? `${((activeRun.result as {best_profit?: number})?.best_profit ?? 0) * 100}%`
                : undefined
            }
            bestTrades={(activeRun.result as {best_trades?: number})?.best_trades}
          />
        )}

        {/* Latest Backtest Result */}
        {latestResult && strategy.status !== "hyperopt_running" && strategy.status !== "backtest_running" && (
          <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-300">
                📊 最新 Backtest 结果（v{latestResult.version}）
              </h3>
              <Link
                href={`/ft-strategy/${strategy.id}/backtest`}
                className="text-xs text-blue-400 hover:underline"
              >
                查看详细报告 →
              </Link>
            </div>
            <div className="grid grid-cols-4 gap-4 text-center">
              {[
                {
                  label: "Win",
                  value: latestResult.aggregate.win_rate >= 0
                    ? `${(latestResult.aggregate.win_rate * 100).toFixed(1)}%`
                    : "—",
                },
                {
                  label: "Sharpe",
                  value:
                    latestResult.aggregate.sharpe >= -999
                      ? latestResult.aggregate.sharpe.toFixed(2)
                      : "—",
                },
                {
                  label: "Max DD",
                  value:
                    latestResult.aggregate.max_dd >= 0
                      ? `${(latestResult.aggregate.max_dd * 100).toFixed(1)}%`
                      : "—",
                },
                {
                  label: "Calmar",
                  value:
                    latestResult.aggregate.calmar >= -999
                      ? latestResult.aggregate.calmar.toFixed(2)
                      : "—",
                },
              ].map(({ label, value }) => (
                <div key={label}>
                  <p className="text-xs text-gray-400">{label}</p>
                  <p className="font-mono text-white">{value}</p>
                </div>
              ))}
            </div>

            {strategy.baseline_comparison && (
              <div className="mt-3 flex gap-4 rounded bg-gray-900 p-2 text-xs">
                <span
                  className={
                    strategy.baseline_comparison.drawdown_ok
                      ? "text-green-400"
                      : "text-red-400"
                  }
                >
                  DD{" "}
                  {strategy.baseline_comparison.drawdown_ok ? "✅" : "❌"}{" "}
                  (
                  {(strategy.baseline_comparison.drawdown_pct * 100).toFixed(1)}
                  % ≤{" "}
                  {(strategy.baseline_comparison.baseline_drawdown_pct * 100).toFixed(
                    1
                  )}
                  %)
                </span>
                <span
                  className={
                    strategy.baseline_comparison.calmar_ok
                      ? "text-green-400"
                      : "text-red-400"
                  }
                >
                  Calmar{" "}
                  {strategy.baseline_comparison.calmar_ok ? "✅" : "❌"}{" "}
                  ({strategy.baseline_comparison.calmar.toFixed(2)} ≥{" "}
                  {strategy.baseline_comparison.baseline_calmar.toFixed(2)})
                </span>
              </div>
            )}
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="rounded border border-red-800 bg-red-950 p-3 text-sm text-red-300">
            {error}
          </div>
        )}

        {/* Deploy Section */}
        {strategy.status === "analyzed" && (
          <div className="rounded-lg border border-gray-700 bg-gray-800 p-4 space-y-3">
            <h3 className="text-sm font-semibold text-gray-300">🚀 申请部署</h3>
            <p className="text-xs text-gray-400">
              点击后服务端将检查全部 9 项 promotion gate。全部通过才创建 PR。
            </p>
            <button
              onClick={handleDeploy}
              disabled={deploying}
              className={`rounded px-4 py-2 text-sm font-medium transition-colors ${
                deploying
                  ? "cursor-not-allowed bg-gray-700 text-gray-400"
                  : "bg-green-700 text-white hover:bg-green-600"
              }`}
            >
              {deploying ? "检查中..." : "🚀 申请部署 PR"}
            </button>
          </div>
        )}

        {strategy.status === "pending_review" && strategy.deployment_pr_url && (
          <div className="rounded-lg border border-yellow-800 bg-yellow-950/40 p-4">
            <p className="text-sm text-yellow-300">
              ✅ 部署 PR 已创建：
              <a
                href={strategy.deployment_pr_url}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-1 text-blue-400 hover:underline"
              >
                查看 PR
              </a>
            </p>
            <p className="mt-1 text-xs text-gray-400">
              等待人类审核并合并 → SIGHUP → 状态更新为 deployed
            </p>
          </div>
        )}

        {strategy.status === "deployed" && (
          <div className="rounded-lg border border-green-800 bg-green-950/40 p-4">
            <p className="text-sm text-green-300">✅ 已上线</p>
          </div>
        )}
      </div>
    </div>
  );
}
