import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BacktestPanel } from "./backtest-panel";
import type { RsiTrendBacktestResponse } from "@/lib/api-rsi-strategy";

const BACKTEST_RESULT: RsiTrendBacktestResponse = {
  market: "binance",
  symbol: "BTCUSDT",
  interval: "4h",
  lookback_days: 180,
  filters: { use_ema50: false, require_candle_color: false, atr_mult: 1.0, partial_mode: false },
  bars: 1080,
  total_signals: 2,
  trades_count: 2,
  win_count: 1,
  loss_count: 1,
  scratch_count: 0,
  win_rate: 0.5,
  avg_r: 0.5,
  total_r: 1.0,
  profit_factor: 2.0,
  max_drawdown_r: 1.0,
  avg_bars_held: 12.5,
  trades: [
    {
      direction: "long",
      entry_price: 60000,
      entry_time: "2026-06-01T00:00:00",
      stop_loss: 59000,
      target_price: 62000,
      exit_price: 62000,
      exit_time: "2026-06-03T00:00:00",
      exit_reason: "target",
      r_multiple: 2.0,
      bars_held: 12,
      partials: [],
    },
    {
      direction: "short",
      entry_price: 58000,
      entry_time: "2026-07-01T00:00:00",
      stop_loss: 59000,
      target_price: 56000,
      exit_price: 59000,
      exit_time: "2026-07-02T00:00:00",
      exit_reason: "stop_loss",
      r_multiple: -1.0,
      bars_held: 13,
      partials: [],
    },
  ],
};

function renderPanel(overrides: Partial<Parameters<typeof BacktestPanel>[0]> = {}) {
  const onBacktest = vi.fn();
  render(
    <BacktestPanel
      result={null}
      loading={false}
      error={null}
      onBacktest={onBacktest}
      {...overrides}
    />
  );
  return { onBacktest };
}

describe("BacktestPanel", () => {
  it("renders the form and backtest button", () => {
    renderPanel();
    expect(screen.getByText("历史回测")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /开始回测/ })).toBeInTheDocument();
  });

  it("submits default params on backtest click", async () => {
    const { onBacktest } = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /开始回测/ }));
    expect(onBacktest).toHaveBeenCalledWith({
      market: "binance",
      symbol: "BTCUSDT",
      interval: "4h",
      use_ema50: false,
      require_candle_color: false,
      atr_mult: 1.0,
      lookback_days: 180,
      partial_mode: false,
    });
  });

  it("shows error message", () => {
    renderPanel({ error: "无法获取行情数据" });
    expect(screen.getByText("无法获取行情数据")).toBeInTheDocument();
  });

  it("renders metrics and trade rows", () => {
    renderPanel({ result: BACKTEST_RESULT });
    expect(screen.getByText("50.0%")).toBeInTheDocument();
    expect(screen.getByText("+2.00R")).toBeInTheDocument();
    expect(screen.getByText("-1.00R")).toBeInTheDocument();
    expect(screen.getByText("止盈(1:2)")).toBeInTheDocument();
    expect(screen.getByText("止损")).toBeInTheDocument();
  });

  it("renders empty-state message when no trades", () => {
    renderPanel({ result: { ...BACKTEST_RESULT, trades: [], trades_count: 0, total_signals: 0 } });
    expect(screen.getByText(/没有产生任何交易信号/)).toBeInTheDocument();
  });

  it("shows the discipline disclaimer", () => {
    renderPanel({ result: BACKTEST_RESULT });
    expect(screen.getByText(/历史回测不代表未来收益/)).toBeInTheDocument();
  });
});
