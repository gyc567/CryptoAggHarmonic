"use client";

import type { PromotionChecklist, PromotionCheckItem } from "@/types/ft-strategy";

interface DeployGateProps {
  checklist: PromotionChecklist;
  onDeploy: () => void;
  deploying: boolean;
  shadowMissing?: boolean; // [ftstrategy-shadow-01] missing
}

function CheckItem({ item }: { item: PromotionCheckItem }) {
  return (
    <div
      className={`flex items-start gap-2 py-1 ${
        item.passed ? "text-green-400" : "text-red-400"
      }`}
    >
      <span className="mt-0.5 text-sm">{item.passed ? "✅" : "❌"}</span>
      <div>
        <span className="text-sm font-medium">{item.label}</span>
        {item.detail && (
          <p className="text-xs text-gray-400">{item.detail}</p>
        )}
      </div>
    </div>
  );
}

export function DeployGate({
  checklist,
  onDeploy,
  deploying,
  shadowMissing,
}: DeployGateProps) {
  const allPassed = checklist.all_passed;

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
        <h3 className="mb-3 text-sm font-semibold text-gray-300">
          🚀 部署检查清单
        </h3>
        <div className="space-y-1">
          {checklist.items.map((item) => (
            <CheckItem key={item.key} item={item} />
          ))}
        </div>
      </div>

      {shadowMissing && (
        <div className="rounded border border-yellow-700 bg-yellow-950/40 p-3 text-xs text-yellow-300">
          ⚠️ 需先完成 7 天 shadow 回放（`[ftstrategy-shadow-01]` durable-fact 未建立），
          UI 隐藏了部署按钮。请在 shadow 完成后手动填入 durable-facts。
        </div>
      )}

      {!allPassed && !shadowMissing && (
        <p className="text-sm text-red-400">
          ❌ 仍有检查项未通过，请修正后再试。
        </p>
      )}

      {allPassed && !shadowMissing && (
        <button
          onClick={onDeploy}
          disabled={deploying}
          className={`rounded px-4 py-2 text-sm font-medium transition-colors ${
            deploying
              ? "cursor-not-allowed bg-gray-700 text-gray-400"
              : "bg-green-700 text-white hover:bg-green-600"
          }`}
        >
          {deploying ? "创建部署 PR..." : "🚀 申请部署 PR"}
        </button>
      )}
    </div>
  );
}
