import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ResultPanel } from "@/components/dashboard/result-panel";
import type { AnalysisData } from "@/types";

const baseResult: AnalysisData = {
  analysis_id: "a-1",
  status: "completed",
  market: "binance",
  symbol: "BTCUSDT",
  interval: "1h",
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
  },
  interpretation: { summary: "形态完成度较高" },
  chart: { format: "png" },
  timing: { duration_ms: 1250 },
};

describe("ResultPanel", () => {
  it("shows loading skeleton", () => {
    render(<ResultPanel result={null} loading={true} error={null} />);
    expect(screen.getByText("正在分析，请稍候...")).toBeInTheDocument();
  });

  it("shows error with request id", () => {
    render(
      <ResultPanel
        result={null}
        loading={false}
        error={{ code: "X", message: "无法获取市场数据", retryable: true, request_id: "r-1" }}
      />
    );
    expect(screen.getByText("分析失败")).toBeInTheDocument();
    expect(screen.getByText("无法获取市场数据")).toBeInTheDocument();
    expect(screen.getByText(/r-1/)).toBeInTheDocument();
  });

  it("shows error without request id", () => {
    render(
      <ResultPanel
        result={null}
        loading={false}
        error={{ code: "X", message: "失败", retryable: false }}
      />
    );
    expect(screen.queryByText(/请求 ID/)).not.toBeInTheDocument();
  });

  it("renders 422 field-level details when present", () => {
    render(
      <ResultPanel
        result={null}
        loading={false}
        error={{
          code: "INVALID_PARAMS",
          message: "请求参数不合法",
          retryable: false,
          status: 422,
          details: [
            { loc: "interval", msg: "Input should be '15m','1h','4h','1d','1w'", type: "literal_error" },
            { loc: "candles", msg: "Input should be greater than or equal to 100", type: "greater_than_equal" },
          ],
        }}
      />
    );
    const list = screen.getByTestId("field-error-list");
    expect(list).toBeInTheDocument();
    expect(screen.getByText("interval")).toBeInTheDocument();
    expect(screen.getByText(/Input should be '15m'/)).toBeInTheDocument();
    expect(screen.getByText("candles")).toBeInTheDocument();
    expect(screen.getByText(/greater than or equal to 100/)).toBeInTheDocument();
  });

  it("falls back to global label when detail.loc is empty (cross-field)", () => {
    render(
      <ResultPanel
        result={null}
        loading={false}
        error={{
          code: "INVALID_PARAMS",
          message: "请求参数不合法",
          retryable: false,
          status: 422,
          details: [{ loc: "", msg: "candles must be >= 2*limit_to", type: "value_error" }],
        }}
      />
    );
    expect(screen.getByText("(全局)")).toBeInTheDocument();
  });

  it("shows empty state with quick tags", () => {
    render(<ResultPanel result={null} loading={false} error={null} />);
    expect(screen.getByText("暂无分析结果")).toBeInTheDocument();
    expect(screen.getByText("BTCUSDT")).toBeInTheDocument();
  });

  it("shows resolved_type badge for auto-formed", () => {
    render(<ResultPanel result={baseResult} loading={false} error={null} />);
    expect(screen.getByText("自动 → 已形成")).toBeInTheDocument();
    expect(screen.getByText("看多 Bullish")).toBeInTheDocument();
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.getByText("形态完成度较高")).toBeInTheDocument();
    expect(screen.getByText(/1\.25s/)).toBeInTheDocument();
  });

  it("shows resolved_type badge for forming", () => {
    render(
      <ResultPanel
        result={{
          ...baseResult,
          technical_result: { ...baseResult.technical_result, resolved_type: "forming" },
        }}
        loading={false}
        error={null}
      />
    );
    expect(screen.getByText("自动 → 形成中")).toBeInTheDocument();
  });

  it("hides badge when resolved_type is null", () => {
    render(
      <ResultPanel
        result={{
          ...baseResult,
          technical_result: { ...baseResult.technical_result, resolved_type: null },
        }}
        loading={false}
        error={null}
      />
    );
    expect(screen.queryByText(/自动 →/)).not.toBeInTheDocument();
  });

  it("shows bearish badge", () => {
    render(
      <ResultPanel
        result={{
          ...baseResult,
          technical_result: { ...baseResult.technical_result, direction: "bearish" },
        }}
        loading={false}
        error={null}
      />
    );
    expect(screen.getByText("看空 Bearish")).toBeInTheDocument();
  });

  it("shows raw status for non-completed non-no_result states", () => {
    render(
      <ResultPanel
        result={{ ...baseResult, status: "failed_model" }}
        loading={false}
        error={null}
      />
    );
    expect(screen.getByText("failed_model")).toBeInTheDocument();
  });

  it("renders signal card when signal is present", () => {
    render(
      <ResultPanel
        result={{
          ...baseResult,
          technical_result: {
            ...baseResult.technical_result,
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
              targets: [],
            },
          },
        }}
        loading={false}
        error={null}
      />
    );
    expect(screen.getByTestId("signal-card")).toBeInTheDocument();
  });

  it("tolerates missing technical_result and interpretation", () => {
    const sparse = {
      ...baseResult,
      technical_result: undefined,
      interpretation: undefined,
    } as unknown as AnalysisData;
    render(<ResultPanel result={sparse} loading={false} error={null} />);
    expect(screen.getByText("技术结果")).toBeInTheDocument();
  });

  it("shows no_result status and hides summary/duration when absent", () => {
    render(
      <ResultPanel
        result={{
          ...baseResult,
          status: "no_result",
          technical_result: {},
          interpretation: {},
          timing: { duration_ms: 0 },
        }}
        loading={false}
        error={null}
      />
    );
    expect(screen.getByText("无结果")).toBeInTheDocument();
    expect(screen.queryByText("模型解读")).not.toBeInTheDocument();
  });
});
