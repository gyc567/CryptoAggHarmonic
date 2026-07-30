"use client";

import type { FuturesQuote } from "@/lib/api-watchlist";

export interface QuoteCellProps {
  quote?: FuturesQuote;
}

function formatPercent(n: number | undefined): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function formatPrice(n: number | undefined): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

export function QuoteCell({ quote }: QuoteCellProps) {
  if (!quote) {
    return (
      <div className="text-xs text-muted-foreground">
        <div>--</div>
        <div>--</div>
      </div>
    );
  }
  const pct = quote.priceChangePercent ?? 0;
  const positive = pct >= 0;
  return (
    <div className="text-right text-xs leading-tight">
      <div className="font-mono text-sm text-foreground">
        {formatPrice(quote.lastPrice)}
      </div>
      <div
        className={
          positive ? "text-emerald-400" : "text-rose-400"
        }
      >
        {formatPercent(quote.priceChangePercent)}
      </div>
    </div>
  );
}