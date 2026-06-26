import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E config for the trading dashboard.
 *
 * `webServer` boots the Vite dev server (port 5173) before the suite and
 * tears it down after. The dev server proxies /api → http://localhost:8000
 * (see vite.config.ts), so the FULL journal→order→close→analytics flow runs
 * end-to-end only when a backend is ALSO listening on :8000 with a seeded
 * test user. Without a backend the spec still runs its public smoke portion
 * (landing + sign-in form), so `npm run test:e2e` is never a hard failure on
 * a frontend-only checkout.
 *
 * Set E2E_EMAIL / E2E_PASSWORD (a pre-seeded account) to unlock the
 * authenticated steps. See e2e/core-flow.spec.ts.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // Reuse an already-running dev server locally; boot one in CI.
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: "npm run dev",
        url: "http://localhost:5173",
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
});
