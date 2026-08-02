"use client";

import { Plus } from "lucide-react";

interface EmptyStateProps {
  onAdd?: () => void;
}

export function EmptyState({ onAdd }: EmptyStateProps) {
  return (
    <div className="rounded-xl border border-dashed border-border-subtle bg-card/30 p-8 text-center">
      <p className="text-lg font-semibold text-foreground">还没有自选合约</p>
      <p className="mt-2 text-sm text-muted-foreground">
        添加你想跟踪的 USDⓈ-M 永续合约。
      </p>
      {onAdd && (
        <button
          type="button"
          onClick={onAdd}
          className="mt-4 inline-flex items-center gap-1 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          <Plus className="h-4 w-4" />
          添加第一个币种
        </button>
      )}
    </div>
  );
}