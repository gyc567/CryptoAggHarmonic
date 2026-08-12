"use client";

import { useEffect, useState, useCallback, use } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/use-auth";
import { BacktestChart } from "@/components/ft-strategy/BacktestChart";
import { DeployGate } from "@/components/ft-strategy/DeployGate";
import { getStrategy, getBacktestReport, deployStrategy, runPreflight } from "@/lib/api-ft-strategy";
import type { FtStrategy, BacktestResult, PromotionChecklist } from "@/types/ft-strategy";

export default function BacktestReportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { user, getToken } = useAuth();

  const [strategy, setStrategy] = useState<FtStrategy | null>(null);
  const [report, setReport] = useState<BacktestResult | null>(null);
  const [checklist, setChecklist] = useState<PromotionChecklist | null>(null);
  const [loading, setLoading] = useState(true);
  const [checklistLoading, setChecklistLoading] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!user) return;
    const token = await getToken();
    if (!token) return;
    const [s, r] = await Promise.all([
      getStrategy(id, token),
      getBacktestReport(id, token).catch(() => null),
    ]);
    setStrategy(s);
    setReport(r);
    setLoading(false);
  }, [user, getToken, id]);

  useEffect(() => {
    load();
  }, [load]);

  async function loadChecklist() {
    if (!user) return;
    setChecklistLoading(true);
    try {
      const token = await getToken();
      if (!token) return;
      const result = await runPreflight(id, token);
      // Build PromotionChecklist from preflight result
      setChecklist({
        all_passed: result.passed,
        items: result.items.map((item) => ({
          key: item.check,
          label: item.check,
          passed: item.passed,
          detail: item.detail,
        })),
      });
    } catch (e) {
      // preflight failed — show error
      setError((e as Error).message);
    } finally {
      setChecklistLoading(false);
    }
  }

  async function handleDeploy() {
    if (!user) return;
    setDeploying(true);
    try {
      const token = await getToken();
      if (!token) return;
      await deployStrategy(id, token);
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
        <p>策略不存在。</p>
        <Link href="/ft-strategy" className="mt-2 text-blue-400 hover:underline">
          ← 返回
        </Link>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6">
      <div className="mx-auto max-w-4xl space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <Link
              href={`/ft-strategy/${id}`}
              className="mb-1 text-sm text-gray-400 hover:text-white"
            >
              ← {strategy.name}
            </Link>
            <h1 className="text-xl font-bold text-white">📊 回测报告</h1>
          </div>
          <div className="flex gap-2">
            {strategy.status === "analyzed" && (
              <button
                onClick={loadChecklist}
                disabled={checklistLoading}
                className={`rounded px-3 py-1.5 text-xs font-medium ${
                  checklistLoading
                    ? "bg-gray-700 text-gray-400"
                    : "bg-blue-700 text-white hover:bg-blue-600"
                }`}
              >
                {checklistLoading ? "检查中..." : "🔍 检查部署资格"}
              </button>
            )}
          </div>
        </div>

        {/* Promotion Checklist */}
        {checklist && (
          <DeployGate
            checklist={checklist}
            onDeploy={handleDeploy}
            deploying={deploying}
            shadowMissing={false}
          />
        )}

        {/* Backtest Charts */}
        {report ? (
          <BacktestChart
            result={report}
            baselineComparison={report.baseline_comparison}
          />
        ) : (
          <div className="rounded border border-dashed border-gray-600 py-16 text-center text-gray-400">
            <p>暂无回测数据</p>
            <p className="mt-1 text-sm">
              回测完成后会显示在此处
            </p>
          </div>
        )}

        {/* Raw blocks download */}
        {report?.raw_blocks && (
          <div className="rounded border border-gray-700 bg-gray-800 p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-medium text-gray-300">原始日志</h3>
              <a
                href={`data:text/plain;charset=utf-8,${encodeURIComponent(report.raw_blocks)}`}
                download={`backtest-${id}.log`}
                className="text-xs text-blue-400 hover:underline"
              >
                下载 .log
              </a>
            </div>
            <pre className="max-h-64 overflow-auto rounded bg-gray-900 p-3 font-mono text-xs text-gray-400">
              {report.raw_blocks.slice(-3000)}
            </pre>
          </div>
        )}

        {error && (
          <div className="rounded border border-red-800 bg-red-950 p-3 text-sm text-red-300">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
