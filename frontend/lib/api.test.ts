import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { analyze, getAnalysis, getHistory, getMarkets } from "@/lib/api";

const ORIGINAL_FETCH = global.fetch;

function mockFetchOnce(body: unknown, init?: { status?: number; ok?: boolean }) {
  const status = init?.status ?? 200;
  const ok = init?.ok ?? (status >= 200 && status < 300);
  const text = typeof body === "string" ? body : JSON.stringify(body);
  global.fetch = vi.fn(async () => {
    return new Response(text, {
      status,
      headers: { "Content-Type": "application/json" },
      statusText: ok ? "OK" : "Error",
      ok,
    });
  }) as unknown as typeof fetch;
}

afterEach(() => {
  global.fetch = ORIGINAL_FETCH;
  vi.restoreAllMocks();
});

describe("api.request", () => {
  describe("analyze()", () => {
    it("unwraps { success, data } envelope on 200", async () => {
      const data = { analysis_id: "a-1" };
      mockFetchOnce({ success: true, data });
      const res = await analyze(null, { market: "binance", symbol: "BTCUSDT", interval: "1h", analysis_type: "auto" });
      expect(res).toEqual({ success: true, data });
    });

    it("falls back to wrapping a non-envelope success body", async () => {
      const data = { markets: ["binance"] };
      mockFetchOnce(data);
      const res = await getMarkets(null);
      expect(res).toEqual({ success: true, data });
    });

    it("returns ApiFailure with parsed details on 422", async () => {
      mockFetchOnce(
        {
          success: false,
          error: {
            code: "INVALID_PARAMS",
            message: "请求参数不合法",
            retryable: false,
            request_id: "req-1",
          },
          details: [
            { loc: "interval", msg: "Input should be '15m','1h'", type: "literal_error" },
            { loc: "candles", msg: "Input should be >= 100", type: "greater_than_equal" },
          ],
        },
        { status: 422 }
      );
      const res = await analyze(null, { market: "binance", symbol: "BTCUSDT", interval: "2h", analysis_type: "auto" });
      expect(res.success).toBe(false);
      if (res.success) throw new Error("expected failure");
      expect(res.error.code).toBe("INVALID_PARAMS");
      expect(res.error.message).toBe("请求参数不合法");
      expect(res.error.retryable).toBe(false);
      expect(res.error.request_id).toBe("req-1");
      expect(res.error.status).toBe(422);
      expect(res.error.details).toHaveLength(2);
      expect(res.error.details?.[0]).toEqual({
        loc: "interval",
        msg: "Input should be '15m','1h'",
        type: "literal_error",
      });
    });

    it("returns ApiFailure with empty details on 422 missing the field", async () => {
      mockFetchOnce(
        {
          success: false,
          error: {
            code: "INVALID_PARAMS",
            message: "bad",
            retryable: false,
          },
        },
        { status: 422 }
      );
      const res = await analyze(null, { market: "binance", symbol: "BTCUSDT", interval: "1h", analysis_type: "auto" });
      expect(res.success).toBe(false);
      if (res.success) throw new Error("expected failure");
      expect(res.error.status).toBe(422);
      expect(res.error.details).toBeUndefined();
    });

    it("treats empty details array as 'no field errors' rather than [].", async () => {
      mockFetchOnce(
        {
          success: false,
          error: { code: "X", message: "y", retryable: false },
          details: [],
        },
        { status: 422 }
      );
      const res = await analyze(null, { market: "binance", symbol: "BTCUSDT", interval: "1h", analysis_type: "auto" });
      expect(res.success).toBe(false);
      if (res.success) throw new Error("expected failure");
      expect(res.error.details).toBeUndefined();
    });

    it("falls back to a generic error when body is unparseable JSON", async () => {
      mockFetchOnce("<html>500 page</html>", { status: 500 });
      const res = await getHistory(null);
      expect(res.success).toBe(false);
      if (res.success) throw new Error("expected failure");
      expect(res.error.code).toBe("HTTP_ERROR");
      expect(res.error.status).toBe(500);
      expect(res.error.retryable).toBe(true);
    });

    it("returns NETWORK error when fetch throws", async () => {
      global.fetch = vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }) as unknown as typeof fetch;
      const res = await getAnalysis(null, "id-1");
      expect(res.success).toBe(false);
      if (res.success) throw new Error("expected failure");
      expect(res.error.code).toBe("NETWORK");
      expect(res.error.retryable).toBe(true);
    });

    it("passes the bearer token when supplied", async () => {
      const spy = vi.fn(async () =>
        new Response(JSON.stringify({ success: true, data: {} }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );
      global.fetch = spy as unknown as typeof fetch;
      await analyze("token-abc", { market: "binance", symbol: "BTCUSDT", interval: "1h", analysis_type: "auto" });
      const call = spy.mock.calls[0];
      const headers = call[1]?.headers as Record<string, string>;
      expect(headers.Authorization).toBe("Bearer token-abc");
    });

    it("omits Authorization header when no token is supplied", async () => {
      const spy = vi.fn(async () =>
        new Response(JSON.stringify({ success: true, data: {} }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );
      global.fetch = spy as unknown as typeof fetch;
      await getHistory(null);
      const call = spy.mock.calls[0];
      const headers = call[1]?.headers as Record<string, string>;
      expect(headers.Authorization).toBeUndefined();
    });
  });
});