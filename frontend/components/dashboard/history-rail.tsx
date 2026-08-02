"use client";

import { useEffect, useState } from "react";
import { Clock, ArrowRight } from "lucide-react";
import { cn, formatDate } from "@/lib/utils";
import { getHistory } from "@/lib/api";
import type { AnalysisHistoryItem } from "@/types";

interface HistoryRailProps {
  getToken: () => Promise<string | null>;
  onRerun?: (item: AnalysisHistoryItem) => void;
  className?: string;
}

export function HistoryRail({ getToken, onRerun, className }: HistoryRailProps) {
  const [items, setItems] = useState<AnalysisHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    getToken()
      .then((token) => (token ? getHistory(token, { retry: 2, retryDelayMs: 300 }) : null))
      .then((res) => {
        if (!mounted || !res) return;
        if ("data" in res) {
          setItems(res.data.items);
        }
      })
      .finally(() => setLoading(false));
    return () => {
      mounted = false;
    };
  }, [getToken]);

  return (
    <section className={cn("glass-card p-5", className)}>
      <div className="mb-4 flex items-center gap-2">
        <Clock className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold text-foreground">最近分析</h3>
      </div>

      {loading ? (
        <div className="space-y-3">
          <div className="h-16 w-full shimmer" />
          <div className="h-16 w-full shimmer" />
        </div>
      ) : items.length === 0 ? (
        <p className="py-6 text-center text-xs text-muted-foreground">
          暂无历史记录
        </p>
      ) : (
        <ul className="space-y-2">
          {items.slice(0, 8).map((item) => (
            <li key={item.analysis_id}>
              <button
                type="button"
                onClick={() => onRerun?.(item)}
                className="group flex w-full items-center justify-between rounded-xl border border-transparent bg-elevated/50 px-3 py-3 text-left transition-all hover:border-border-accent hover:bg-muted"
              >
                <div>
                  <p className="text-sm font-medium text-foreground">
                    {item.symbol} · {item.interval}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {formatDate(item.created_at)}
                  </p>
                </div>
                <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
