"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/hooks/use-auth";
import { useWatchlist } from "@/hooks/use-watchlist";
import { EmptyState } from "@/components/watchlist/empty-state";
import { SymbolSearch } from "@/components/watchlist/symbol-search";
import { WatchlistTable } from "@/components/watchlist/watchlist-table";

export default function WatchlistPage() {
  const router = useRouter();
  const { user, loading: authLoading, getToken } = useAuth();
  const [toast, setToast] = useState<string | null>(null);

  const wl = useWatchlist({
    getToken,
    onError: (m) => setToast(m),
    onSuccess: (m) => setToast(m),
  });

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace("/login");
    }
  }, [authLoading, user, router]);

  useEffect(() => {
    if (!toast) return;
    const handle = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(handle);
  }, [toast]);

  if (authLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  const limit = wl.limit;

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <header>
        <h1 className="text-2xl font-bold text-foreground">自选币种</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          跟踪 USDⓈ-M 永续合约的最新价格与 24h 变化。最多 {limit} 个。
        </p>
      </header>

      <SymbolSearch
        results={wl.searchResults}
        loading={wl.loadingSearch}
        onSearch={(q) => {
          void wl.searchSymbols(q);
        }}
        onPick={(sym) => {
          void wl.add(sym);
        }}
      />

      {wl.loadingList ? (
        <div className="rounded-xl border border-border-subtle bg-card/40 p-6 text-center text-sm text-muted-foreground">
          加载中…
        </div>
      ) : wl.items.length === 0 ? (
        <EmptyState />
      ) : (
        <WatchlistTable
          items={wl.items}
          quotes={wl.quotes}
          loadingQuotes={wl.loadingQuotes}
          onUpdate={(id, patch) => wl.update(id, patch)}
          onRemove={(id) => wl.remove(id)}
          onMove={(id, dir) => wl.move(id, dir)}
        />
      )}

      {toast && (
        <div className="fixed bottom-6 right-6 rounded-lg border border-border-subtle bg-card px-4 py-2 text-sm shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}