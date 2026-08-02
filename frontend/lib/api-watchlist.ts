// Watchlist API wrappers (frontend/lib/api-watchlist.ts).
//
// All endpoints are thin wrappers around `request<T>` from `@/lib/api`. The
// backend route definitions live in `app/api/watchlist_routes.py`; this file
// only owns the wire shape (TS types + fetch calls).

import { request } from "@/lib/api";
import type { ApiResponse } from "@/types";

export interface FuturesSymbol {
  symbol: string;
  baseAsset: string;
  quoteAsset: string;
  contractType: string;
  underlyingType: string;
  underlyingSubTypes?: string[];
  pricePrecision?: number;
  quantityPrecision?: number;
  status?: string;
  isTradfi?: boolean;
}

export interface FuturesSymbolsResponse {
  count: number;
  results: FuturesSymbol[];
}

export interface WatchlistItem {
  id: string;
  user_id: string;
  symbol: string;
  market: string;
  base_asset?: string;
  quote_asset?: string;
  underlying_type?: string;
  contract_type?: string;
  sort_index: number;
  note: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface WatchlistListResponse {
  items: WatchlistItem[];
  limit: number;
}

export interface WatchlistItemResponse {
  item: WatchlistItem;
}

export interface FuturesQuote {
  symbol: string;
  lastPrice?: number;
  priceChangePercent?: number;
  markPrice?: number;
  fundingRate?: number;
  nextFundingTime?: number;
  highPrice?: number;
  lowPrice?: number;
  volume?: number;
  quoteVolume?: number;
  count?: number;
}

export interface BatchQuotesResponse {
  quotes: FuturesQuote[];
  unknown: string[];
}

// ---------------------------------------------------------------------------
// Symbol search
// ---------------------------------------------------------------------------

export async function searchFuturesSymbols(
  token: string | null,
  q: string,
  signal?: AbortSignal,
): Promise<ApiResponse<FuturesSymbolsResponse>> {
  const params = q ? `?q=${encodeURIComponent(q)}` : "";
  return request<FuturesSymbolsResponse>(
    `/api/markets/futures/symbols${params}`,
    token,
    { signal },
  );
}

// ---------------------------------------------------------------------------
// Watchlist CRUD
// ---------------------------------------------------------------------------

export async function listWatchlist(
  token: string | null,
): Promise<ApiResponse<WatchlistListResponse>> {
  return request<WatchlistListResponse>("/api/watchlist", token);
}

export async function addToWatchlist(
  token: string | null,
  symbol: string,
  note?: string,
): Promise<ApiResponse<WatchlistItemResponse>> {
  return request<WatchlistItemResponse>("/api/watchlist", token, {
    method: "POST",
    body: JSON.stringify({ symbol, note: note ?? "" }),
  });
}

export async function updateWatchlistItem(
  token: string | null,
  id: string,
  patch: { note?: string | null; sort_index?: number },
): Promise<ApiResponse<WatchlistItemResponse>> {
  return request<WatchlistItemResponse>(`/api/watchlist/${id}`, token, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteWatchlistItem(
  token: string | null,
  id: string,
): Promise<ApiResponse<{ deleted: boolean; id: string }>> {
  return request<{ deleted: boolean; id: string }>(
    `/api/watchlist/${id}`,
    token,
    { method: "DELETE" },
  );
}

export async function reorderWatchlist(
  token: string | null,
  orderedIds: string[],
): Promise<ApiResponse<{ items: WatchlistItem[] }>> {
  return request<{ items: WatchlistItem[] }>("/api/watchlist/reorder", token, {
    method: "POST",
    body: JSON.stringify({
      items: orderedIds.map((id, sort_index) => ({ id, sort_index })),
    }),
  });
}

// ---------------------------------------------------------------------------
// Batch quotes
// ---------------------------------------------------------------------------

export async function batchQuotes(
  token: string | null,
  symbols: string[],
): Promise<ApiResponse<BatchQuotesResponse>> {
  const q = symbols.join(",");
  return request<BatchQuotesResponse>(
    `/api/markets/futures/quote?symbols=${encodeURIComponent(q)}`,
    token,
  );
}