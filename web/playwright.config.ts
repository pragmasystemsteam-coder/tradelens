import { defineConfig } from "@playwright/test";

// E2E smoke scripts (Detailed Design 7.7). Run through `python scripts/e2e.py`, which starts
// a throwaway stack and sets E2E_BASE_URL and the test users. The installed Google Chrome is
// used (channel "chrome"), so no Playwright browser download is needed.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3100",
    channel: process.env.E2E_CHANNEL ?? "chrome",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
  },
});
