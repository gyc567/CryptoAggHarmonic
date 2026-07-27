import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ScanPanel } from "./scan-panel";
import type { RsiTrendScanResponse } from "@/lib/api-rsi-strategy";

const SCAN_RESULT: RsiTrendScanResponse = {
  market: "binance",
  symbol: "BTCUSDT",
  interval: "4h",
  filters: { use_ema50: false, require_candle_color: false, atr_mult: 1.0, rsi_zone: "pullback", reward_risk: 2.0, min_quality_score: 30 },
  bars: 500,
  state: {
    time: "2026-07-24T12:00:00",
    close: 65000,
    ema200: 60000,
    ema50: 63000,
    rsi: 35.5,
    atr: 800,
    trend: "bullish",
    deviation_pct: 8.33,
    entangled: false,
  },
  latest_signal: {
    direction: "long",
    entry_price: 65000,
    stop_loss: 63600,
    target_price: 67800,
    atr: 800,
    rsi: 32.1,
    time: "2026-07-24T12:00:00",
    index: 499,
    quality_score: 72,
  },
  recent_signals: [
    {
      direction: "long",
      entry_price: 65000,
      stop_loss: 63600,
      target_price: 67800,
      atr: 800,
      rsi: 32.1,
      time: "2026-07-24T12:00:00",
      index: 499,
      quality_score: 72,
    },
  ],
};

function renderPanel(overrides: Partial<Parameters<typeof ScanPanel>[0]> = {}) {
  const onScan = vi.fn();
  render(
    <ScanPanel result={null} loading={false} error={null} onScan={onScan} {...overrides} />
  );
  return { onScan };
}

describe("ScanPanel", () => {
  it("renders the form and scan button", () => {
    renderPanel();
    expect(screen.getByText("信号扫描")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /开始扫描/ })).toBeInTheDocument();
  });

  it("submits default params on scan click", async () => {
    const { onScan } = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /开始扫描/ }));
    expect(onScan).toHaveBeenCalledWith({
      market: "binance",
      symbol: "BTCUSDT",
      interval: "4h",
      use_ema50: false,
      require_candle_color: false,
      atr_mult: 1.0,
      rsi_zone: "pullback",
      reward_risk: 2.0,
      min_quality_score: 30,
    });
  });

  it("resets symbol and interval when switching to stocks", async () => {
    const { onScan } = renderPanel();
    await userEvent.selectOptions(screen.getAllByRole("combobox")[0], "yahoo");
    await userEvent.click(screen.getByRole("button", { name: /开始扫描/ }));
    expect(onScan).toHaveBeenCalledWith(
      expect.objectContaining({ market: "yahoo", symbol: "AAPL", interval: "1d" })
    );
  });

  it("shows error message", () => {
    renderPanel({ error: "每日额度已用完" });
    expect(screen.getByText("每日额度已用完")).toBeInTheDocument();
  });

  it("renders state and latest signal", () => {
    renderPanel({ result: SCAN_RESULT });
    expect(screen.getByText("多头环境")).toBeInTheDocument();
    expect(screen.getByText("+8.33%")).toBeInTheDocument();
    expect(screen.getByText("最新信号")).toBeInTheDocument();
    expect(screen.getAllByText("做多").length).toBeGreaterThan(0);
    expect(screen.getAllByText("63,600.00").length).toBeGreaterThan(0);
  });

  it("warns when price is entangled with EMA200", () => {
    renderPanel({
      result: {
        ...SCAN_RESULT,
        latest_signal: null,
        recent_signals: [],
        state: { ...SCAN_RESULT.state, entangled: true },
      },
    });
    expect(screen.getByText(/EMA200 附近缠绕/)).toBeInTheDocument();
    expect(screen.getByText(/没有符合过滤条件的信号/)).toBeInTheDocument();
  });
});
