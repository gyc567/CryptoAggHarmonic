import { test, expect } from "@playwright/test";

test.describe("注册与登录流程", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
  });

  test("注册页应展示邮箱密码表单", async ({ page }) => {
    await page.goto("/register");

    await expect(page.getByRole("heading", { name: "创建账号" })).toBeVisible();
    await expect(page.getByPlaceholder("you@example.com")).toBeVisible();
    await expect(page.getByPlaceholder("至少 8 个字符")).toBeVisible();
    await expect(page.getByPlaceholder("再次输入密码")).toBeVisible();
    await expect(page.getByRole("button", { name: "注册" })).toBeVisible();
  });

  test("登录页应展示 OTP 和密码两个 Tab", async ({ page }) => {
    await page.goto("/login");

    await expect(page.getByText("魔法链接")).toBeVisible();
    await expect(page.getByText("密码登录")).toBeVisible();
    // Default tab is OTP
    await expect(page.getByPlaceholder("you@example.com")).toBeVisible();
    await expect(page.getByRole("button", { name: "发送登录链接" })).toBeVisible();
  });

  test("登录页应能切换到密码 Tab 并显示密码表单", async ({ page }) => {
    await page.goto("/login");

    await page.getByText("密码登录").click();
    await expect(page.getByPlaceholder("you@example.com")).toBeVisible();
    await expect(page.getByPlaceholder("输入密码")).toBeVisible();
    await expect(page.getByRole("button", { name: "密码登录" })).toBeVisible();
  });

  test("注册页密码验证：两次输入不一致应报错", async ({ page }) => {
    await page.goto("/register");

    await page.getByPlaceholder("you@example.com").fill("test@example.com");
    await page.getByPlaceholder("至少 8 个字符").fill("password123");
    await page.getByPlaceholder("再次输入密码").fill("differentpass");
    await page.getByRole("button", { name: "注册" }).click();

    await expect(page.getByText("两次输入的密码不一致")).toBeVisible();
  });

  test("注册页密码过短应报错", async ({ page }) => {
    await page.goto("/register");

    await page.getByPlaceholder("you@example.com").fill("test@example.com");
    await page.getByPlaceholder("至少 8 个字符").fill("123");
    await page.getByPlaceholder("再次输入密码").fill("123");
    await page.getByRole("button", { name: "注册" }).click();

    await expect(page.getByText("密码至少 8")).toBeVisible();
  });

  test("已有账号链接应跳转到登录页", async ({ page }) => {
    await page.goto("/register");

    await page.getByRole("link", { name: "登录" }).click();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("登录页切换到密码 Tab 后切换回 OTP Tab", async ({ page }) => {
    await page.goto("/login");

    await page.getByText("密码登录").click();
    await expect(page.getByPlaceholder("输入密码")).toBeVisible();

    await page.getByText("魔法链接").click();
    await expect(page.getByPlaceholder("you@example.com")).toBeVisible();
    await expect(page.getByRole("button", { name: "发送登录链接" })).toBeVisible();
  });
});
