// Watchlist hook (frontend/hooks/use-watchlist.ts).
//
// Owns: list of items, in-flight CRUD ops, quote refresh, error/success
// toasts via callbacks. Uses pure callbacks (toast) rather than a UI library
// to stay framework-neutral.

"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  addToWatchlist,
  batchQuotes,
  deleteWatchlistItem,
  listWatchlist,
  reorderWatchlist,
  searchFuturesSymbols,
  updateWatchlistItem,
  type FuturesQuote,
  type FuturesSymbol,
  type WatchlistItem,
} from "@/lib/api-watchlist";

export interface UseWatchlistOptions {
  getToken: () => Promise<string | null>;
  /** Called on soft errors (no toast UI in this hook itself). */
  onError?: (message: string) => void;
  /** Called on successful add / delete / reorder so the page can flash a toast. */
  onSuccess?: (message: string) => void;
}

export interface UseWatchlistResult {
  items: WatchlistItem[];
  quotes: Record<string, FuturesQuote>;
  loadingList: boolean;
  loadingQuotes: boolean;
  loadingSearch: boolean;
  searchResults: FuturesSymbol[];
  error: string | null;
  reload: () => Promise<void>;
  searchSymbols: (q: string) => Promise<void>;
  add: (symbol: string, note?: string) => Promise<boolean>;
  update: (
    id: string,
    patch: { note?: string | null; sort_index?: number },
  ) => Promise<boolean>;
  remove: (id: string) => Promise<boolean>;
  move: (id: string, direction: "up" | "down") => Promise<boolean>;
  reloadQuotes: () => Promise<void>;
  limit: number;
}

const QUOTE_REFRESH_DEBOUNCE_MS = 30_000;

export function useWatchlist({
  getToken,
  onError,
  onSuccess,
}: UseWatchlistOptions): UseWatchlistResult {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [quotes, setQuotes] = useState<Record<string, FuturesQuote>>({});
  const [loadingList, setLoadingList] = useState(false);
  const [loadingQuotes, setLoadingQuotes] = useState(false);
  const [loadingSearch, setLoadingSearch] = useState(false);
  const [searchResults, setSearchResults] = useState<FuturesSymbol[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(50);

  const lastQuoteFetchAtRef = useRef<number>(0);
  const searchAbortRef = useRef<AbortController | null>(null);

  // ----- list -----

  const reload = useCallback(async () => {
    setLoadingList(true);
    setError(null);
    try {
      const token = await getToken();
      if (!token) {
        setError("未登录");
        return;
      }
      const res = await listWatchlist(token);
      if (res.success) {
        setItems(res.data.items ?? []);
        setLimit(res.data.limit ?? 50);
      } else {
        setError(res.error.message);
      }
    } finally {
      setLoadingList(false);
    }
  }, [getToken]);

  // ----- search -----

  const searchSymbols = useCallback(
    async (q: string) => {
      searchAbortRef.current?.abort();
      const controller = new AbortController();
      searchAbortRef.current = controller;
      setLoadingSearch(true);
      try {
        const token = await getToken();
        if (!token) {
          setSearchResults([]);
          return;
        }
        const res = await searchFuturesSymbols(token, q, controller.signal);
        if (controller.signal.aborted) return;
        if (res.success) {
          setSearchResults(res.data.results ?? []);
        } else {
          setSearchResults([]);
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoadingSearch(false);
        }
      }
    },
    [getToken],
  );

  // ----- quote refresh -----

  const reloadQuotes = useCallback(async () => {
    if (items.length === 0) {
      setQuotes({});
      return;
    }
    const now = Date.now();
    if (now - lastQuoteFetchAtRef.current < QUOTE_REFRESH_DEBOUNCE_MS) {
      return;
    }
    lastQuoteFetchAtRef.current = now;
    setLoadingQuotes(true);
    try {
      const token = await getToken();
      if (!token) return;
      const symbols = items.map((it) => it.symbol);
      const res = await batchQuotes(token, symbols);
      if (res.success) {
        const map: Record<string, FuturesQuote> = {};
        for (const q of res.data.quotes ?? []) {
          map[q.symbol] = q;
        }
        setQuotes(map);
      }
    } finally {
      setLoadingQuotes(false);
    }
  }, [items, getToken]);

  // ----- mutations -----

  const add = useCallback(
    async (symbol: string, note?: string): Promise<boolean> => {
      const token = await getToken();
      if (!token) {
        setError("未登录");
        return false;
      }

      // Optimistic update: insert a placeholder at the top while the POST
      // is in flight so the UI feels instant.
      const optimisticId = `optimistic-${symbol}-${Date.now()}`;
      const optimisticItem: WatchlistItem = {
        id: optimisticId,
        user_id: "",
        symbol,
        market: "futures",
        note: note ?? "",
        sort_index: 0,
      };
      setItems((prev) => {
        const shifted = prev.map((it) => ({ ...it, sort_index: it.sort_index + 1 }));
        return [optimisticItem, ...shifted];
      });

      const res = await addToWatchlist(token, symbol, note);
      if (res.success) {
        onSuccess?.(`${symbol} 已添加到自选`);
        await reload();
        return true;
      }

      // Roll back on failure.
      setItems((prev) => prev.filter((it) => it.id !== optimisticId));
      onError?.(res.error.message);
      setError(res.error.message);
      return false;
    },
    [getToken, onError, onSuccess, reload],
  );

  const update = useCallback(
    async (
      id: string,
      patch: { note?: string | null; sort_index?: number },
    ): Promise<boolean> => {
      const token = await getToken();
      if (!token) return false;
      const res = await updateWatchlistItem(token, id, patch);
      if (res.success) {
        setItems((prev) =>
          prev.map((it) => (it.id === id ? { ...it, ...res.data.item } : it)),
        );
        return true;
      }
      onError?.(res.error.message);
      setError(res.error.message);
      return false;
    },
    [getToken, onError],
  );

  const remove = useCallback(
    async (id: string): Promise<boolean> => {
      const token = await getToken();
      if (!token) return false;
      const res = await deleteWatchlistItem(token, id);
      if (res.success) {
        setItems((prev) => prev.filter((it) => it.id !== id));
        onSuccess?.("已删除");
        return true;
      }
      onError?.(res.error.message);
      setError(res.error.message);
      return false;
    },
    [getToken, onError, onSuccess],
  );

  const move = useCallback(
    async (id: string, direction: "up" | "down"): Promise<boolean> => {
      const idx = items.findIndex((it) => it.id === id);
      if (idx === -1) return false;
      const target = direction === "up" ? idx - 1 : idx + 1;
      if (target < 0 || target >= items.length) return false;

      const reordered = [...items];
      const [moved] = reordered.splice(idx, 1);
      reordered.splice(target, 0, moved);
      const orderedIds = reordered.map((it) => it.id);

      // Optimistic update.
      setItems(
        reordered.map((it, sort_index) => ({ ...it, sort_index })),
      );

      const token = await getToken();
      if (!token) return false;
      const res = await reorderWatchlist(token, orderedIds);
      if (res.success) {
        return true;
      }
      // Roll back on failure.
      await reload();
      onError?.(res.error.message);
      setError(res.error.message);
      return false;
    },
    [items, getToken, onError, reload],
  );

  // Auto-load on mount; quote refresh once items settle.
  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (items.length === 0) return;
    reloadQuotes();
  }, [items, reloadQuotes]);

  return {
    items,
    quotes,
    loadingList,
    loadingQuotes,
    loadingSearch,
    searchResults,
    error,
    reload,
    searchSymbols,
    add,
    update,
    remove,
    move,
    reloadQuotes,
    limit,
  };
}