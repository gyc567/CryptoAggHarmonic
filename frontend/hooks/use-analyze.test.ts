import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAnalyze } from "@/hooks/use-analyze";

describe("useAnalyze default form", () => {
  it("defaults the interval to 4h for crypto markets", () => {
    // useAnalyze uses module-level process.env.NEXT_PUBLIC_DEFAULT_MARKET.
    // We leave the env untouched (default = "binance") and just verify the
    // initial form picks 4h, matching the dashboard's documented default.
    const getToken = vi.fn().mockResolvedValue("token");
    const { result } = renderHook(() => useAnalyze(getToken));
    expect(result.current.form.interval).toBe("4h");
    expect(result.current.form.market).toBe("binance");
    // First symbol in the binance list should be auto-selected so the form
    // is submittable on first paint.
    expect(result.current.form.symbol).not.toBe("");
  });

  it("exposes the markets helper for the form to load on mount", () => {
    const getToken = vi.fn().mockResolvedValue("token");
    const { result } = renderHook(() => useAnalyze(getToken));
    expect(typeof result.current.loadMarkets).toBe("function");
    expect(typeof result.current.submit).toBe("function");
    expect(typeof result.current.updateField).toBe("function");
  });
});
