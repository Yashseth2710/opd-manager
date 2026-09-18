import { defineConfig, devices } from "@playwright/test";
import { SHARED_STATE } from "./e2e/state";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  // One worker, deliberately. Setting up a clinic is rate limited to a
  // handful an hour from one address, which is right for a sign-up form and
  // means a run cannot afford a clinic per worker. Tests share one and name
  // their own doctors, and the database round trip dominates the wall clock
  // either way.
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],

  // Generous, because the database is in another region and a cold Next
  // route compiles on first request.
  timeout: 90_000,
  expect: { timeout: 20_000 },

  use: {
    baseURL: BASE_URL,
    storageState: SHARED_STATE,
    // Kept for the attempt that failed, not the retry after it. A test that
    // stalls once and then passes is the one worth a trace, and recording
    // only the retry kept the run that explained nothing.
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: {
    command: "npm run dev",
    url: `${BASE_URL}/login`,
    reuseExistingServer: true,
    timeout: 180_000,
  },
});
