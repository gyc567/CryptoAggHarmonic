"use client";

import { useState } from "react";

import { QuoteCell } from "@/components/watchlist/quote-cell";
import type {
  FuturesQuote,
  WatchlistItem,
} from "@/lib/api-watchlist";

export interface WatchlistTableProps {
  items: WatchlistItem[];
  quotes: Record<string, FuturesQuote>;
  loadingQuotes: boolean;
  onUpdate: (
    id: string,
    patch: { note?: string | null; sort_index?: number },
  ) => Promise<boolean>;
  onRemove: (id: string) => Promise<boolean>;
  onMove: (id: string, direction: "up" | "down") => Promise<boolean>;
}

function rowClass(sym: string, quote: FuturesQuote | undefined): string {
  if (quote && (quote.lastPrice === undefined || quote.lastPrice === null)) {
    return "opacity-50";
  }
  return "";
}

export function WatchlistTable({
  items,
  quotes,
  loadingQuotes,
  onUpdate,
  onRemove,
  onMove,
}: WatchlistTableProps) {
  const [editingNoteFor, setEditingNoteFor] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState("");

  if (items.length === 0) return null;

  return (
    <div className="rounded-xl border border-border-subtle bg-card/40">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-subtle text-xs uppercase text-muted-foreground">
            <th className="w-10 px-2 py-2">#</th>
            <th className="px-3 py-2 text-left">合约</th>
            <th className="px-3 py-2 text-left">备注</th>
            <th className="px-3 py-2 text-right">最新 / 24h</th>
            <th className="w-32 px-2 py-2 text-right">操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => {
            const quote = quotes[item.symbol];
            const editing = editingNoteFor === item.id;
            return (
              <tr
                key={item.id}
                className={`border-b border-border-subtle last:border-0 ${rowClass(item.symbol, quote)}`}
              >
                <td className="px-2 py-2 text-center text-xs text-muted-foreground">
                  {idx + 1}
                </td>
                <td className="px-3 py-2">
                  <div className="font-mono text-foreground">{item.symbol}</div>
                  <div className="text-xs text-muted-foreground">
                    {item.underlying_type ?? "—"}
                  </div>
                </td>
                <td className="px-3 py-2">
                  {editing ? (
                    <div className="flex gap-2">
                      <input
                        className="flex-1 rounded border border-border-subtle bg-background px-2 py-1 text-xs"
                        value={noteDraft}
                        maxLength={280}
                        onChange={(e) => setNoteDraft(e.target.value)}
                      />
                      <button
                        className="text-xs text-primary"
                        onClick={async () => {
                          await onUpdate(item.id, { note: noteDraft });
                          setEditingNoteFor(null);
                        }}
                      >
                        保存
                      </button>
                      <button
                        className="text-xs text-muted-foreground"
                        onClick={() => setEditingNoteFor(null)}
                      >
                        取消
                      </button>
                    </div>
                  ) : (
                    <button
                      className="text-left text-xs text-muted-foreground hover:text-foreground"
                      onClick={() => {
                        setNoteDraft(item.note ?? "");
                        setEditingNoteFor(item.id);
                      }}
                    >
                      {item.note || "添加备注…"}
                    </button>
                  )}
                </td>
                <td className="px-3 py-2">
                  <QuoteCell quote={quote} />
                </td>
                <td className="px-2 py-2 text-right">
                  <div className="flex justify-end gap-1 text-xs">
                    <button
                      disabled={idx === 0}
                      className="rounded border border-border-subtle px-2 py-1 disabled:opacity-30"
                      onClick={() => onMove(item.id, "up")}
                    >
                      ↑
                    </button>
                    <button
                      disabled={idx === items.length - 1}
                      className="rounded border border-border-subtle px-2 py-1 disabled:opacity-30"
                      onClick={() => onMove(item.id, "down")}
                    >
                      ↓
                    </button>
                    <button
                      className="rounded border border-rose-500/40 px-2 py-1 text-rose-400 hover:bg-rose-500/10"
                      onClick={() => {
                        if (confirm(`删除 ${item.symbol}?`)) {
                          void onRemove(item.id);
                        }
                      }}
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {loadingQuotes && (
        <div className="border-t border-border-subtle px-3 py-1 text-right text-xs text-muted-foreground">
          刷新行情中…
        </div>
      )}
    </div>
  );
}