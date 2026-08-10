import { test, expect } from "@playwright/test";
import { mockSupabaseOtp } from "./helpers";

test.describe("认证流程", () => {
  test("未登录访问首页应重定向到登录页", async ({ page }) => {
    await page.goto("/");
    await page.waitForURL("/login");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("未登录访问 /dashboard 应重定向到登录页", async ({ page }) => {
    await page.goto("/dashboard");
    await page.waitForURL("/login");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("登录页应展示邮箱表单并支持 OTP 提交", async ({ page }) => {
    await mockSupabaseOtp(page);
    await page.goto("/login");

    await expect(page.getByRole("heading", { name: "CryptoAgg" })).toBeVisible();
    await expect(page.getByPlaceholder("you@example.com")).toBeVisible();
    await expect(page.getByRole("button", { name: "发送魔法链接" })).toBeVisible();

    await page.getByPlaceholder("you@example.com").fill("e2e-user@cryptoagg.app");
    await page.getByRole("button", { name: "发送魔法链接" }).click();

    await expect(page.getByText("魔法链接已发送")).toBeVisible();
    await expect(page.getByText("e2e-user@cryptoagg.app")).toBeVisible();
  });
});
