"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { createStrategy } from "@/lib/api-ft-strategy";
import type { IdeaSource, CreateFtStrategyRequest } from "@/types/ft-strategy";

const RESEARCH_MD_TEMPLATE = `## Decision
What is the core hypothesis? What market inefficiency are you exploiting?

## Question
What specific question does this strategy attempt to answer?

## Motivation
Why does this strategy make sense for this market and timeframe?

## Universe
What markets/pairs/intervals does this apply to?

## Constraints
What are the hard boundaries? (max drawdown, min trades, etc.)

## Failure Modes
What would cause this strategy to fail? What signals should trigger abandonment?

## Open Qs
What remains unresolved? What would you investigate if you had more time?
`.trim();

// Count sections present in research_md
function countSections(md: string): number {
  const sections = [
    "## Decision",
    "## Question",
    "## Motivation",
    "## Universe",
    "## Constraints",
    "## Failure Modes",
    "## Open Qs",
  ];
  return sections.filter((s) => md.includes(s)).length;
}

export default function NewFtStrategyPage() {
  const router = useRouter();
  const { user, getToken } = useAuth();

  const [form, setForm] = useState({
    name: "",
    marketType: "futures" as const,
    pair: "BTC/USDT",
    interval: "5m",
    ideaSource: "template" as IdeaSource,
    template: "rsi_mean_reversion",
    naturalLanguage: "",
    hyperoptMinutes: 30,
    maxCandidates: 5,
  });

  const [researchMd, setResearchMd] = useState(RESEARCH_MD_TEMPLATE);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const charCount = researchMd.length;
  const sectionCount = countSections(researchMd);
  const isValid = charCount >= 200 && sectionCount >= 7;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!user) return;
    if (!isValid) {
      setError("research_md 必须 ≥ 200 字符且包含全部 7 个章节");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const token = await getToken();
      if (!token) return;
      const body: CreateFtStrategyRequest = {
        name: form.name,
        idea_source: form.ideaSource,
        idea_payload:
          form.ideaSource === "natural_language"
            ? { text: form.naturalLanguage }
            : form.ideaSource === "clone"
            ? { forked_from: "" }
            : { template: form.template, hyperopt_minutes: form.hyperoptMinutes, max_candidates: form.maxCandidates },
        research_md: researchMd,
        market_type: form.marketType,
        pair: form.pair,
        interval: form.interval,
      };
      const strategy = await createStrategy(body, token);
      router.push(`/ft-strategy/${strategy.id}`);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <div className="p-4 sm:p-6">
      <div className="mx-auto max-w-2xl">
        <h1 className="mb-6 text-2xl font-bold text-white">💡 创建新 FT 策略</h1>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Basic Info */}
          <div className="rounded-lg border border-gray-700 bg-gray-800 p-4 space-y-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">策略名称</label>
              <input
                type="text"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full rounded bg-gray-900 border border-gray-600 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
                placeholder="例如：BTC RSI 均值回归 v1"
              />
            </div>

            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">市场</label>
                <select
                  value={form.marketType}
                  onChange={(e) => setForm({ ...form, marketType: e.target.value as "futures" })}
                  className="w-full rounded bg-gray-900 border border-gray-600 px-2 py-2 text-white"
                >
                  <option value="futures">Binance Futures</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">交易对</label>
                <select
                  value={form.pair}
                  onChange={(e) => setForm({ ...form, pair: e.target.value })}
                  className="w-full rounded bg-gray-900 border border-gray-600 px-2 py-2 text-white"
                >
                  {["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","XRP/USDT"].map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">周期</label>
                <select
                  value={form.interval}
                  onChange={(e) => setForm({ ...form, interval: e.target.value })}
                  className="w-full rounded bg-gray-900 border border-gray-600 px-2 py-2 text-white"
                >
                  {["1m","5m","15m","1h","4h","1d"].map((i) => (
                    <option key={i} value={i}>{i}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* Idea Source */}
          <div className="rounded-lg border border-gray-700 bg-gray-800 p-4 space-y-4">
            <p className="text-sm text-gray-400">策略思路</p>
            <div className="flex gap-4">
              {(["template","natural_language","clone"] as IdeaSource[]).map((src) => (
                <label key={src} className="flex items-center gap-2 text-sm text-gray-300">
                  <input
                    type="radio"
                    name="ideaSource"
                    value={src}
                    checked={form.ideaSource === src}
                    onChange={() => setForm({ ...form, ideaSource: src })}
                    className="text-blue-500"
                  />
                  {src === "template" ? "模板策略" : src === "natural_language" ? "自然语言" : "复制现有"}
                </label>
              ))}
            </div>

            {form.ideaSource === "template" && (
              <div className="space-y-2">
                <select
                  value={form.template}
                  onChange={(e) => setForm({ ...form, template: e.target.value })}
                  className="w-full rounded bg-gray-900 border border-gray-600 px-3 py-2 text-white"
                >
                  <option value="rsi_mean_reversion">RSI 均值回归</option>
                  <option value="bollinger_breakout">Bollinger 突破</option>
                  <option value="macd_cross">MACD 交叉</option>
                  <option value="harmonic_pattern">Harmonic Pattern</option>
                </select>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <label className="text-gray-400">hyperopt 时长</label>
                    <input
                      type="number"
                      min={5}
                      max={30}
                      value={form.hyperoptMinutes}
                      onChange={(e) => setForm({ ...form, hyperoptMinutes: Number(e.target.value) })}
                      className="mt-1 w-full rounded bg-gray-900 border border-gray-600 px-2 py-1 text-white"
                    />
                  </div>
                  <div>
                    <label className="text-gray-400">最大候选数</label>
                    <input
                      type="number"
                      min={1}
                      max={5}
                      value={form.maxCandidates}
                      onChange={(e) => setForm({ ...form, maxCandidates: Number(e.target.value) })}
                      className="mt-1 w-full rounded bg-gray-900 border border-gray-600 px-2 py-1 text-white"
                    />
                  </div>
                </div>
              </div>
            )}

            {form.ideaSource === "natural_language" && (
              <textarea
                value={form.naturalLanguage}
                onChange={(e) => setForm({ ...form, naturalLanguage: e.target.value })}
                className="w-full rounded bg-gray-900 border border-gray-600 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
                rows={4}
                placeholder="描述你的策略思路，例如：当 RSI 低于 30 且价格触及布林带下轨时买入..."
              />
            )}
          </div>

          {/* Clarify-first Research MD */}
          <div className="rounded-lg border border-blue-800 bg-blue-950/20 p-4">
            <div className="mb-2 flex items-center justify-between">
              <label className="text-sm font-medium text-blue-300">
                📋 研究简报（clarify-first，required）
              </label>
              <span className={`text-xs ${charCount >= 200 ? "text-green-400" : "text-gray-400"}`}>
                {charCount} / 200 字符 · {sectionCount} / 7 章节
              </span>
            </div>
            <p className="mb-3 text-xs text-gray-400">
              强制填写。AI agent 必须先理解你的意图，才能生成符合预期的策略代码。
            </p>
            <textarea
              value={researchMd}
              onChange={(e) => setResearchMd(e.target.value)}
              className="w-full rounded bg-gray-900 border border-gray-600 px-3 py-2 font-mono text-sm text-gray-200 placeholder-gray-600 focus:border-blue-500 focus:outline-none"
              rows={18}
              placeholder={RESEARCH_MD_TEMPLATE}
            />
          </div>

          {error && (
            <div className="rounded border border-red-800 bg-red-950 p-3 text-sm text-red-300">
              {error}
            </div>
          )}

          <div className="flex items-center justify-end gap-4">
            <button
              type="button"
              onClick={() => router.back()}
              className="rounded px-4 py-2 text-sm text-gray-400 hover:text-white"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submitting || !isValid}
              className={`rounded px-6 py-2 text-sm font-medium transition-colors ${
                submitting || !isValid
                  ? "cursor-not-allowed bg-gray-700 text-gray-400"
                  : "bg-blue-600 text-white hover:bg-blue-500"
              }`}
            >
              {submitting ? "创建中..." : "💡 生成策略 →"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
