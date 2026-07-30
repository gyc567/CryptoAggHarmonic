import { test, expect } from "@playwright/test";
import {
  enableE2EAuth,
  mockAnalyzeSuccess,
  mockAnalyzeNoResult,
  mockAnalyzeError,
  mockHistoryEmpty,
} from "./helpers";

test.describe("分析工作台 (已登录)", () => {
  test.beforeEach(async ({ page, context }) => {
    await enableE2EAuth(context);
    await mockHistoryEmpty(page);
    await page.goto("/dashboard");
  });

  test("页面应加载分析表单与历史侧边栏", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "新建分析" })).toBeVisible();
    await expect(page.getByText("最近分析")).toBeVisible();
    await expect(page.getByRole("button", { name: "开始分析" })).toBeVisible();
  });

  test("市场、标的、周期、分析类型下拉应有选项", async ({ page }) => {
    const marketSelect = page.locator("select").nth(0);
    await expect(marketSelect).toContainText("Binance");
    await expect(marketSelect).toContainText("Yahoo");

    const symbolSelect = page.locator("select").nth(1);
    await expect(symbolSelect).toContainText("BTCUSDT");
    await expect(symbolSelect).toContainText("ETHUSDT");

    const intervalSelect = page.locator("select").nth(2);
    await expect(intervalSelect).toContainText("1h");

    const typeSelect = page.locator("select").nth(3);
    await expect(typeSelect).toContainText("自动设置");
    await expect(typeSelect).toContainText("形成中");
    await expect(typeSelect).toContainText("背离");
  });

  test("分析类型默认值应为自动设置", async ({ page }) => {
    const typeSelect = page.locator("select").nth(3);
    await expect(typeSelect).toHaveValue("auto");
    await expect(typeSelect.locator("option").first()).toHaveText("自动设置");
  });

  test("提交分析后应展示结果面板", async ({ page }) => {
    await mockAnalyzeSuccess(page);

    await page.locator("select").nth(1).selectOption("BTCUSDT");
    await page.getByRole("button", { name: "开始分析" }).click();

    await expect(page.getByText("技术结果")).toBeVisible();
    await expect(page.getByText("BINANCE · BTCUSDT · 1h")).toBeVisible();
    await expect(page.getByText("看多 Bullish")).toBeVisible();
    await expect(page.getByText("形态完成度较高")).toBeVisible();
  });

  test("分析结果应展示交易信号卡片", async ({ page }) => {
    await mockAnalyzeSuccess(page);

    await page.locator("select").nth(1).selectOption("BTCUSDT");
    await page.getByRole("button", { name: "开始分析" }).click();

    await expect(page.getByTestId("signal-card")).toBeVisible();
    await expect(page.getByText("交易信号")).toBeVisible();
    await expect(page.getByText("A级")).toBeVisible();
    await expect(page.getByText("硬止损")).toBeVisible();
    await expect(page.getByText(/阶梯止盈/)).toBeVisible();
    await expect(page.getByText(/共振评分 80\/100/)).toBeVisible();
    await expect(page.getByText("自动 → 已形成")).toBeVisible();
  });

  test("无结果场景应展示无结果状态", async ({ page }) => {
    await mockAnalyzeNoResult(page);

    await page.locator("select").nth(1).selectOption("BTCUSDT");
    await page.getByRole("button", { name: "开始分析" }).click();

    await expect(page.getByText("无结果")).toBeVisible();
  });

  test("分析接口报错应展示错误信息", async ({ page }) => {
    await mockAnalyzeError(page);

    await page.locator("select").nth(1).selectOption("BTCUSDT");
    await page.getByRole("button", { name: "开始分析" }).click();

    await expect(page.getByText("分析失败")).toBeVisible();
    await expect(page.getByText("无法获取市场数据")).toBeVisible();
  });

  test("标的下拉应包含主流币种与股票代币", async ({ page }) => {
    const symbolSelect = page.locator("select").nth(1);
    await expect(symbolSelect).toContainText("BTCUSDT");
    await expect(symbolSelect).toContainText("SOXLBUSDT");
    await expect(symbolSelect).toContainText("SKHYBUSDT");

    await page.locator("select").nth(0).selectOption("yahoo");
    await expect(symbolSelect).toContainText("AAPL");
    await expect(symbolSelect).toContainText("TSLA");
  });
});
