import { defineConfig } from "@playwright/test";

/**
 * E2E against a running stack (SDD §13.2 phone viewport tests).
 *   API:  uvicorn on :8000 (POKER_COOKIE_SECURE=false for http)
 *   Web:  NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run build && npm start
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    locale: "zh-TW", // UI language follows the browser; the spec uses Chinese labels
    trace: "retain-on-failure",
    actionTimeout: 10_000, // a click on a stale/disabled control fails fast instead of hanging
    screenshot: "only-on-failure",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
});
