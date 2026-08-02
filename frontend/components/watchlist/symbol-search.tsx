"use client";

import { useEffect, useRef, useState } from "react";

import type { FuturesSymbol } from "@/lib/api-watchlist";

export interface SymbolSearchProps {
  results: FuturesSymbol[];
  loading: boolean;
  onSearch: (q: string) => void;
  onPick: (symbol: string) => void;
  onClose?: () => void;
  autoFocus?: boolean;
  placeholder?: string;
  disabledSymbols?: string[];
}

export function SymbolSearch({
  results,
  loading,
  onSearch,
  onPick,
  onClose,
  autoFocus = false,
  placeholder = "搜索币种 (例如 MU, BTC, 苹果)",
  disabledSymbols = [],
}: SymbolSearchProps) {
  const [q, setQ] = useState("");
  const wrapperRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const disabledSet = new Set(disabledSymbols);

  useEffect(() => {
    const handle = setTimeout(() => onSearch(q), 250);
    return () => clearTimeout(handle);
  }, [q, onSearch]);

  useEffect(() => {
    if (autoFocus) {
      inputRef.current?.focus();
    }
  }, [autoFocus]);

  // Close on Escape or clicking outside the search box.
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose?.();
      }
    };

    const handlePointerDown = (e: PointerEvent) => {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(e.target as Node)
      ) {
        onClose?.();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [onClose]);

  const handlePick = (symbol: string, disabled: boolean) => {
    if (disabled) return;
    onPick(symbol);
    setQ("");
  };

  return (
    <div ref={wrapperRef} className="relative">
      <input
        ref={inputRef}
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
          {results.slice(0, 12).map((s) => {
            const disabled = disabledSet.has(s.symbol);
            return (
              <li key={s.symbol}>
                <button
                  type="button"
                  disabled={disabled}
                  className={`flex w-full items-center justify-between px-4 py-2 text-left text-sm ${
                    disabled
                      ? "cursor-not-allowed opacity-50"
                      : "hover:bg-elevated"
                  }`}
                  onClick={() => handlePick(s.symbol, disabled)}
                  title={disabled ? "已在自选列表中" : undefined}
                >
                  <span className="font-mono">{s.symbol}</span>
                  <span className="text-xs text-muted-foreground">
                    {disabled
                      ? "已添加"
                      : `${s.baseAsset} · ${s.underlyingType}${s.isTradfi ? " · TradFi" : ""}`}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}