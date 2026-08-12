"use client";

interface HyperoptProgressProps {
  progressPct: number;
  elapsed?: string;
  total?: string;
  candidates?: number;
  bestProfit?: string;
  bestTrades?: number;
  onCancel?: () => void;
}

export function HyperoptProgress({
  progressPct,
  elapsed,
  total,
  candidates,
  bestProfit,
  bestTrades,
  onCancel,
}: HyperoptProgressProps) {
  const pct = Math.min(100, Math.max(0, progressPct));
  const bars = Math.round(pct / 10);

  return (
    <div className="rounded-lg border border-blue-800 bg-blue-950/40 p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-blue-300">⚡ Hyperopt 运行中</span>
        <span className="text-sm text-blue-200">{pct}%</span>
      </div>

      <div className="mb-2 flex h-3 overflow-hidden rounded-full bg-gray-700">
        {Array.from({ length: 10 }).map((_, i) => (
          <div
            key={i}
            className={`h-full transition-all ${
              i < bars ? "bg-blue-500" : i === bars ? "bg-blue-300 animate-pulse" : "bg-gray-700"
            }`}
            style={{ width: "10%" }}
          />
        ))}
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-blue-200">
        {elapsed && total && (
          <span>
            Elapsed: <strong>{elapsed}</strong> / {total}
          </span>
        )}
        {candidates !== undefined && (
          <span>
            Candidates: <strong>{candidates}</strong>
          </span>
        )}
        {bestProfit && (
          <span>
            Best profit: <strong>{bestProfit}</strong>
          </span>
        )}
        {bestTrades !== undefined && (
          <span>
            Best trades: <strong>{bestTrades}</strong>
          </span>
        )}
      </div>

      {onCancel && (
        <button
          onClick={onCancel}
          className="mt-2 rounded border border-red-700 bg-red-950 px-3 py-1 text-xs text-red-300 hover:bg-red-900"
        >
          终止
        </button>
      )}
    </div>
  );
}
