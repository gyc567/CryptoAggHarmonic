"use client";

import { useEffect, useState } from "react";

import type { FuturesSymbol } from "@/lib/api-watchlist";

export interface SymbolSearchProps {
  results: FuturesSymbol[];
  loading: boolean;
  onSearch: (q: string) => void;
  onPick: (symbol: string) => void;
  placeholder?: string;
}

export function SymbolSearch({
  results,
  loading,
  onSearch,
  onPick,
  placeholder = "搜索币种 (例如 MU, BTC, 苹果)",
}: SymbolSearchProps) {
  const [q, setQ] = useState("");

  useEffect(() => {
    const handle = setTimeout(() => onSearch(q), 250);
    return () => clearTimeout(handle);
  }, [q, onSearch]);

  return (
    <div className="relative">
      <input
        type="search"
        className="w-full rounded-lg border border-border-subtle bg-card/60 px-4 py-2 text-sm placeholder:text-muted-foreground focus:border-primary focus:outline-none"
        placeholder={placeholder}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {loading && (
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
          …
        </span>
      )}
      {results.length > 0 && (
        <ul className="absolute left-0 right-0 z-20 mt-1 max-h-72 overflow-auto rounded-lg border border-border-subtle bg-card shadow-lg">
          {results.slice(0, 12).map((s) => (
            <li key={s.symbol}>
              <button
                type="button"
                className="flex w-full items-center justify-between px-4 py-2 text-left text-sm hover:bg-elevated"
                onClick={() => {
                  onPick(s.symbol);
                  setQ("");
                }}
              >
                <span className="font-mono">{s.symbol}</span>
                <span className="text-xs text-muted-foreground">
                  {s.baseAsset} · {s.underlyingType}
                  {s.isTradfi ? " · TradFi" : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}