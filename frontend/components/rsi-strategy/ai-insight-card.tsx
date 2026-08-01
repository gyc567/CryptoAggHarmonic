"use client";

import { BrainCircuit } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RsiTrendPlan } from "@/lib/api-rsi-strategy";

interface Props {
  insight: NonNullable<RsiTrendPlan["ai_insight"]>;
  className?: string;
}

export function AiInsightCard({ insight, className }: Props) {
  return (
    <section className={cn("glass-card p-5 sm:p-6", className)}>
      <div className="mb-3 flex items-center gap-2">
        <BrainCircuit className="h-4 w-4 text-primary" />
        <h2 className="text-sm font-semibold text-foreground">
          AI 解读
          {insight.cached && (
            <span className="ml-2 text-xs text-muted-foreground">(缓存)</span>
          )}
        </h2>
      </div>

      <p className="text-sm text-foreground/90 leading-relaxed">
        {insight.summary}
      </p>

      {insight.risk_note && (
        <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
          ⚠ {insight.risk_note}
        </p>
      )}

      <p className="mt-3 text-xs text-muted-foreground/60 italic">
        {insight.disclaimer}
      </p>
    </section>
  );
}
