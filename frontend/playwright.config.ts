import { defineConfig, devices } from "@playwright/test";
import path from "path";

const PROJECT_ROOT = path.resolve(__dirname, "..");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [["html", { outputFolder: "e2e-report" }], ["list"]],
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: `${PROJECT_ROOT}/.venv/bin/python -m app.main`,
      cwd: PROJECT_ROOT,
      env: {
        PORT: "5050",
        DISABLE_AUTH: "1",
      },
      url: "http://127.0.0.1:5050/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: "npm run dev",
      cwd: __dirname,
      env: {
        NEXT_PUBLIC_API_BASE: "",
        BACKEND_API_BASE: "http://127.0.0.1:5050",
        // Required by isSupabaseConfigured() in lib/supabase/client.ts so the
        // login page doesn't render the "Supabase 未配置" banner. The OTP
        // endpoint is mocked per-test via mockSupabaseOtp().
        NEXT_PUBLIC_SUPABASE_URL: "https://e2e-test.supabase.co",
        NEXT_PUBLIC_SUPABASE_ANON_KEY: "e2e-test-anon-key-padded",
      },
      url: "http://127.0.0.1:3000/login",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
