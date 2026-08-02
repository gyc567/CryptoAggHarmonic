import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ResultPanel } from "@/components/dashboard/result-panel";
import type { AnalysisData } from "@/types";

const baseResult: AnalysisData = {
  analysis_id: "a-1",
  status: "completed",
  market: "binance",
  symbol: "BTCUSDT",
  interval: "4h",
  analysis_type: "auto",
  parameters: {},
  technical_result: {
    direction: "bullish",
    pattern_family: "XABCD",
    pattern_type: "gartley",
    confidence: "high",
    risk_reward_ratio: 2.5,
    entry_price: 65000,
    stop_loss: 64000,
    target_price: 67500,
    resolved_type: "formed",
    current_price: 64800,
    current_price_at: "2026-08-02T04:00:00+00:00",
  },
  interpretation: { summary: "形态完成度较高" },
  timing: { duration_ms: 1250 },
};

describe("ResultPanel current price cell", () => {
  it("renders the realtime price prominently when current_price is set", () => {
    render(<ResultPanel result={baseResult} loading={false} error={null} />);
    const card = screen.getByTestId("current-price-card");
    expect(card).toBeInTheDocument();
    // The large price text should be present (formatted with thousand separators).
    expect(card.textContent).toContain("64,800.00");
  });

  it("renders the entry-distance badge with the correct sign for longs below entry", () => {
    // current 64800 vs entry 65000 → -0.31% (approaching for a long)
    render(<ResultPanel result={baseResult} loading={false} error={null} />);
    const badge = screen.getByTestId("entry-distance");
    expect(badge.textContent).toMatch(/-0\.31%/);
  });

  it("renders the timestamp when current_price_at is set", () => {
    render(<ResultPanel result={baseResult} loading={false} error={null} />);
    expect(screen.getByText(/数据截至/)).toBeInTheDocument();
    expect(screen.getByText(/2026-08-02T04:00:00/)).toBeInTheDocument();
  });

  it("omits the realtime card when current_price is null", () => {
    const sparse: AnalysisData = {
      ...baseResult,
      technical_result: { ...baseResult.technical_result, current_price: null },
    };
    render(<ResultPanel result={sparse} loading={false} error={null} />);
    expect(screen.queryByTestId("current-price-card")).not.toBeInTheDocument();
  });

  it("omits the realtime card on no_result when current_price wasn't extracted", () => {
    const noPrice: AnalysisData = {
      ...baseResult,
      status: "no_result",
      technical_result: {},
      interpretation: {},
      timing: { duration_ms: 0 },
    };
    render(<ResultPanel result={noPrice} loading={false} error={null} />);
    expect(screen.queryByTestId("current-price-card")).not.toBeInTheDocument();
  });

  it("renders the realtime card on no_result when current_price was extracted", () => {
    // Real-world scenario: no harmonic pattern, but the latest close was
    // still extracted from the candle window — show it.
    const noPattern: AnalysisData = {
      ...baseResult,
      status: "no_result",
      technical_result: {
        current_price: 65500,
        current_price_at: "2026-08-02T04:00:00+00:00",
      },
      interpretation: { summary: "未检测到明显的谐波形态。" },
      timing: { duration_ms: 800 },
    };
    render(<ResultPanel result={noPattern} loading={false} error={null} />);
    expect(screen.getByTestId("current-price-card")).toBeInTheDocument();
    expect(screen.getByText("65,500.00")).toBeInTheDocument();
  });

  it("renders the bearish flag with the right sign convention", () => {
    // For a bearish setup, current 0.77% ABOVE entry means price has
    // already broken above the resistance — the harmonic setup is
    // invalidated, so the badge should NOT render as 'approaching'
    // (i.e. should use the warning color, not success). The signed %
    // rendering is unchanged.
    const bearish: AnalysisData = {
      ...baseResult,
      technical_result: {
        ...baseResult.technical_result,
        direction: "bearish",
        entry_price: 65000,
        current_price: 65500, // 0.77% above entry
      },
    };
    render(<ResultPanel result={bearish} loading={false} error={null} />);
    const badge = screen.getByTestId("entry-distance");
    expect(badge.textContent).toMatch(/\+0\.77%/);
    // Warning class, not success — bearish + above entry is invalidated.
    expect(badge.className).toMatch(/text-warning/);
    expect(badge.className).not.toMatch(/text-success/);
  });

  it("marks bearish setup with current below entry as approaching", () => {
    // For a bearish setup, current BELOW entry means price is on its way
    // UP toward the resistance PRZ. The badge should render as success
    // (approaching). This is the symmetric counterpart of the bullish
    // approaching case in the basic test above.
    const bearishApproaching: AnalysisData = {
      ...baseResult,
      technical_result: {
        ...baseResult.technical_result,
        direction: "bearish",
        entry_price: 65000,
        current_price: 64500, // -0.77% below entry
      },
    };
    render(<ResultPanel result={bearishApproaching} loading={false} error={null} />);
    const badge = screen.getByTestId("entry-distance");
    expect(badge.textContent).toMatch(/-0\.77%/);
    expect(badge.className).toMatch(/text-success/);
    expect(badge.className).not.toMatch(/text-warning/);
  });

  it("marks bullish setup with current above entry as approaching", () => {
    // For a bullish setup, current ABOVE entry means price is on its way
    // DOWN toward the support PRZ — the trader is waiting for the pullback.
    const bullishApproaching: AnalysisData = {
      ...baseResult,
      technical_result: {
        ...baseResult.technical_result,
        direction: "bullish",
        entry_price: 65000,
        current_price: 65500, // +0.77% above entry
      },
    };
    render(<ResultPanel result={bullishApproaching} loading={false} error={null} />);
    const badge = screen.getByTestId("entry-distance");
    expect(badge.textContent).toMatch(/\+0\.77%/);
    expect(badge.className).toMatch(/text-success/);
  });

  it("marks bullish setup with current below entry as warning (invalidated)", () => {
    // For a bullish setup, current BELOW entry means price has already
    // broken below the support — the harmonic setup is invalidated.
    const bullishInvalidated: AnalysisData = {
      ...baseResult,
      technical_result: {
        ...baseResult.technical_result,
        direction: "bullish",
        entry_price: 65000,
        current_price: 64500, // -0.77% below entry
      },
    };
    render(<ResultPanel result={bullishInvalidated} loading={false} error={null} />);
    const badge = screen.getByTestId("entry-distance");
    expect(badge.textContent).toMatch(/-0\.77%/);
    expect(badge.className).toMatch(/text-warning/);
    expect(badge.className).not.toMatch(/text-success/);
  });

  it("does not show entry-distance badge when entry_price is missing", () => {
    const noEntry: AnalysisData = {
      ...baseResult,
      technical_result: {
        ...baseResult.technical_result,
        entry_price: undefined,
      },
    };
    render(<ResultPanel result={noEntry} loading={false} error={null} />);
    expect(screen.getByTestId("current-price-card")).toBeInTheDocument();
    expect(screen.queryByTestId("entry-distance")).not.toBeInTheDocument();
  });
});
