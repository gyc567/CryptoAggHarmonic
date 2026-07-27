import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./test-setup.ts"],
    exclude: ["node_modules", ".next", "e2e"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      include: [
        "app/position/**/*",
        "components/position/**/*",
        "components/ui/progress-stacked.tsx",
        "hooks/use-position.ts",
        "lib/position/**/*",
        "lib/symbols.ts",
        "components/dashboard/signal-card.tsx",
        "components/dashboard/analyze-form.tsx",
        "components/dashboard/result-panel.tsx",
        "components/error-boundary/chunk-error-boundary.tsx",
      ],
      exclude: ["node_modules", ".next", "**/*.d.ts"],
      thresholds: {
        lines: 100,
        functions: 100,
        branches: 100,
        statements: 100,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./"),
    },
  },
});
