// Vitest tests for the watchlist API wrapper.
//
// Scope: pure JS contracts only — no DOM, no React. The fetch calls
// are mocked so we don't hit a backend.

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  addToWatchlist,
  batchQuotes,
  deleteWatchlistItem,
  listWatchlist,
  reorderWatchlist,
  searchFuturesSymbols,
  updateWatchlistItem,
} from "@/lib/api-watchlist";

const TOKEN = "test-token";

const mockFetch = (body: unknown, status = 200) => {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(JSON.stringify(body)),
  });
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("searchFuturesSymbols", () => {
  it("calls /api/markets/futures/symbols with ?q=", async () => {
    const payload = {
      success: true,
      data: { count: 1, results: [{ symbol: "MUUSDT", baseAsset: "MU", quoteAsset: "USDT" }] },
    };
    const fetchMock = mockFetch(payload);
    vi.stubGlobal("fetch", fetchMock);

    const res = await searchFuturesSymbols(TOKEN, "MU");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [calledUrl] = fetchMock.mock.calls[0];
    expect(String(calledUrl)).toContain("/api/markets/futures/symbols?q=MU");
    expect(res.success).toBe(true);
  });

  it("omits ?q when query is empty", async () => {
    const fetchMock = mockFetch({ success: true, data: { count: 0, results: [] } });
    vi.stubGlobal("fetch", fetchMock);

    await searchFuturesSymbols(TOKEN, "");
    const [calledUrl] = fetchMock.mock.calls[0];
    expect(String(calledUrl)).toMatch(/\/api\/markets\/futures\/symbols$/);
  });
});

describe("listWatchlist", () => {
  it("returns the items array on success", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({
        success: true,
        data: { items: [{ id: "x", symbol: "MUUSDT" }], limit: 50 },
      }),
    );

    const res = await listWatchlist(TOKEN);
    expect(res.success).toBe(true);
    if (res.success) {
      expect(res.data.items).toHaveLength(1);
      expect(res.data.limit).toBe(50);
    }
  });
});

describe("addToWatchlist", () => {
  it("POSTs symbol and note as JSON", async () => {
    const fetchMock = mockFetch({
      success: true,
      data: { item: { id: "1", symbol: "MUUSDT" } },
    });
    vi.stubGlobal("fetch", fetchMock);

    await addToWatchlist(TOKEN, "MUUSDT", "my note");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/watchlist");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ symbol: "MUUSDT", note: "my note" });
  });

  it("translates duplicate into ApiFailure", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch(
        {
          success: false,
          error: { code: "DUPLICATE_SYMBOL", message: "已在自选中", retryable: false },
        },
        409,
      ),
    );

    const res = await addToWatchlist(TOKEN, "MUUSDT");
    expect(res.success).toBe(false);
    if (!res.success) {
      expect(res.error.code).toBe("DUPLICATE_SYMBOL");
      expect(res.error.status).toBe(409);
    }
  });
});

describe("updateWatchlistItem", () => {
  it("PATCHes the URL", async () => {
    const fetchMock = mockFetch({ success: true, data: { item: { id: "abc" } } });
    vi.stubGlobal("fetch", fetchMock);

    await updateWatchlistItem(TOKEN, "abc", { note: "updated" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/watchlist/abc");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ note: "updated" });
  });
});

describe("deleteWatchlistItem", () => {
  it("DELETEs the URL", async () => {
    const fetchMock = mockFetch({ success: true, data: { deleted: true, id: "abc" } });
    vi.stubGlobal("fetch", fetchMock);

    await deleteWatchlistItem(TOKEN, "abc");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/watchlist/abc");
    expect(init.method).toBe("DELETE");
  });
});

describe("reorderWatchlist", () => {
  it("POSTs items with sort_index", async () => {
    const fetchMock = mockFetch({ success: true, data: { items: [] } });
    vi.stubGlobal("fetch", fetchMock);

    await reorderWatchlist(TOKEN, ["b", "a", "c"]);
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      items: [
        { id: "b", sort_index: 0 },
        { id: "a", sort_index: 1 },
        { id: "c", sort_index: 2 },
      ],
    });
  });
});

describe("batchQuotes", () => {
  it("joins symbols with comma in ?symbols=", async () => {
    const fetchMock = mockFetch({
      success: true,
      data: { quotes: [{ symbol: "MUUSDT", lastPrice: 100 }], unknown: [] },
    });
    vi.stubGlobal("fetch", fetchMock);

    await batchQuotes(TOKEN, ["MUUSDT", "BTCUSDT"]);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("symbols=MUUSDT%2CBTCUSDT");
  });
});