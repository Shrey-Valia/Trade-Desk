import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Vitest config is kept separate from vite.config.ts so the dev/build
// pipeline (the Vite config) stays free of test-only settings. The `@`
// alias and the React plugin are mirrored here so `@/...` imports and JSX
// resolve the same way under the jsdom test runner as they do in the app.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // Playwright specs live under e2e/ and run with their own runner, not
    // vitest — exclude them so `vitest run` doesn't try to collect them.
    exclude: ["**/node_modules/**", "**/dist/**", "e2e/**"],
  },
});
