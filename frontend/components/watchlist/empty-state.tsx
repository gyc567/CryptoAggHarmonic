"use client";

export function EmptyState() {
  return (
    <div className="rounded-xl border border-dashed border-border-subtle bg-card/30 p-8 text-center">
      <p className="text-lg font-semibold text-foreground">还没有自选合约</p>
      <p className="mt-2 text-sm text-muted-foreground">
        使用上方搜索框，添加你想跟踪的 USDⓈ-M 永续合约。
      </p>
    </div>
  );
}