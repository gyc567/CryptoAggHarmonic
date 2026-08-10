import { test, expect } from "@playwright/test";
import { enableE2EAuth } from "./helpers";

test("debug auth state", async ({ page, context }) => {
  await enableE2EAuth(context);
  await page.goto("/dashboard");
  await page.waitForTimeout(3000);
  const ls = await page.evaluate(() => localStorage.getItem("cryptoagg:e2e-auth"));
  const body = await page.locator("body").innerText();
  console.log("localStorage:", ls);
  console.log("body:", body.slice(0, 500));
});
