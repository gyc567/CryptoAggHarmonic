"use client";

import type { FtStatus } from "@/types/ft-strategy";

const STAGES = [
  { key: "draft", label: "💡", name: "Idea" },
  { key: "code_generated", label: "🔧", name: "Code" },
  { key: "hyperopt_running", label: "⚡", name: "Hyperopt" },
  { key: "backtest_running", label: "📊", name: "Backtest" },
  { key: "analyzed", label: "🔍", name: "Analyze" },
  { key: "refining", label: "🔄", name: "Refine" },
  { key: "pending_review", label: "🚀", name: "Deploy" },
] as const;

const DONE_STATUSES = new Set<FtStatus>([
  "code_generated",
  "hyperopt_running",
  "backtest_running",
  "analyzed",
  "refining",
  "pending_review",
  "deployed",
]);

const ACTIVE_STATUSES = new Set<FtStatus>([
  "hyperopt_running",
  "backtest_running",
  "refining",
]);

function stageIndex(status: FtStatus): number {
  if (status === "draft") return 0;
  if (status === "deployed") return STAGES.length - 1;
  const idx = STAGES.findIndex((s) => s.key === status);
  return idx >= 0 ? idx : 0;
}

interface StageProgressProps {
  status: FtStatus;
}

export function StageProgress({ status }: StageProgressProps) {
  const active = ACTIVE_STATUSES.has(status);
  const currentIdx = stageIndex(status);
  const done = DONE_STATUSES.has(status);

  return (
    <div className="flex items-center gap-1">
      {STAGES.map((stage, i) => {
        const isDone = i < currentIdx || (done && i < STAGES.length - 1);
        const isActive = i === currentIdx && active;
        const isLast = i === STAGES.length - 1;

        return (
          <div key={stage.key} className="flex items-center">
            <div
              className={`
                flex h-7 w-7 items-center justify-center rounded-full text-xs
                transition-colors
                ${isDone ? "bg-green-600 text-white" : ""}
                ${isActive ? "bg-blue-600 text-white animate-pulse" : ""}
                ${!isDone && !isActive ? "bg-gray-700 text-gray-400" : ""}
              `}
              title={`${stage.name}${isDone ? " ✓" : isActive ? " (active)" : ""}`}
            >
              {stage.label}
            </div>
            {!isLast && (
              <div
                className={`h-0.5 w-4 ${
                  i < currentIdx ? "bg-green-600" : "bg-gray-700"
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
