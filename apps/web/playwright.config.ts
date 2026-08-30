import { defineConfig, devices } from "@playwright/test";

// FINTRACK-51 batch (FINTRACK-52..58): E2E tier of the testing pyramid --
// critical user journeys only (~15%), everything else is unit/component
// (vitest) per the QA Lead constraint matrix. Requires the full stack
// (Postgres, apps/api, and a built/served apps/web) running at BASE_URL --
// not something this repo's CI wires up yet (see the "does not run vitest
// either" gap flagged in the QA envelope). Specs are written against
// data-testid selectors only, real API calls, no UI-only setup.
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:5173";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: "html",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
