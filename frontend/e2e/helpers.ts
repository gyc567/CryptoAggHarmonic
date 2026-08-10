import type { Page, BrowserContext } from "@playwright/test";

export async function enableE2EAuth(context: BrowserContext) {
  await context.addInitScript(() => {
    window.localStorage.setItem("cryptoagg:e2e-auth", "true");
  });
}

export function mockSupabaseOtp(page: Page) {
  return page.route(
    (url) => url.toString().includes("/auth/v1/otp"),
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({}),
      });
    }
  );
}

export function mockAnalyzeSuccess(page: Page, overrides: Record<string, unknown> = {}) {
  return page.route("/api/analyze", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          analysis_id: "e2e-analysis-1",
          status: "completed",
          market: "binance",
          symbol: "BTCUSDT",
          interval: "1h",
          analysis_type: "forming",
          parameters: {},
          technical_result: {
            direction: "bullish",
            pattern_family: "XABCD",
            pattern_type: "gartley",
            confidence: 0.82,
            risk_reward_ratio: 2.5,
            entry_price: 65000,
            stop_loss: 64000,
            target_price: 67500,
            resolved_type: "formed",
            signal: {
              status: "confirmed",
              grade: "A",
              direction: "long",
              pattern_name: "gartley",
              family: "XABCD",
              formed: true,
              entry_zone: [64800, 65200],
              entry_reference: 65000,
              stop_loss: 64000,
              stop_basis: "X/PRZ invalidation - 0.5*ATR",
              targets: [
                { label: "TP1", price: 66200, fib_basis: "AD 38.2% retrace", close_pct: 50, move_stop_to: "breakeven" },
                { label: "TP2", price: 67500, fib_basis: "AD 61.8% retrace", close_pct: 30, move_stop_to: "tp1" },
                { label: "TP3", price: 71000, fib_basis: "AD 127.2% extension", close_pct: 20, move_stop_to: "trail 1*ATR" },
              ],
              net_rr_tp1: 1.2,
              net_rr_tp2: 2.5,
              confluence_score: 80,
              confluence: { price_action: 25, htf_trend: 25, rsi: 15 },
              htf_trend: "bullish",
              invalidation: 64000,
            },
          },
          interpretation: {
            summary: "形态完成度较高，建议关注突破确认。",
          },
          timing: {
            duration_ms: 1250,
          },
          ...overrides,
        },
      }),
    });
  });
}

export function mockAnalyzeNoResult(page: Page) {
  return page.route("/api/analyze", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          analysis_id: "e2e-analysis-none",
          status: "no_result",
          market: "binance",
          symbol: "BTCUSDT",
          interval: "1h",
          analysis_type: "forming",
          parameters: {},
          technical_result: {},
          interpretation: { summary: "未检测到明显形态。" },
          timing: { duration_ms: 800 },
        },
      }),
    });
  });
}

export function mockAnalyzeError(page: Page) {
  return page.route("/api/analyze", async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({
        success: false,
        error: {
          code: "MARKET_DATA_UNAVAILABLE",
          message: "无法获取市场数据",
          retryable: true,
        },
      }),
    });
  });
}

export function mockHistoryEmpty(page: Page) {
  return page.route("/api/history*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: { items: [], total: 0 },
      }),
    });
  });
}

export function mockMarkets(page: Page) {
  return page.route("/api/markets*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          markets: ["binance", "yahoo"],
          intervals: ["15m", "1h", "4h", "1d", "1w"],
          analysis_types: ["auto", "forming", "formed", "divergence"],
        },
      }),
    });
  });
}
