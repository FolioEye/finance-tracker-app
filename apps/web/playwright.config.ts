import { defineConfig, devices } from "@playwright/test";

// FINTRACK-51 batch (FINTRACK-52..58): E2E tier of the testing pyramid --
// critical user journeys only (~15%), everything else is unit/component
// (vitest) per the QA Lead constraint matrix. Specs are written against
// data-testid selectors only, real API calls, no UI-only setup.
//
// FINTRACK-65: this tier is now actually EXECUTED by CI. Until then the
// specs existed in the tree and ran nowhere -- @playwright/test was installed
// on every CI run and never invoked, so the suite read as coverage while
// contributing none. The `e2e` job in .github/workflows/ci-cd.yml stands up
// Postgres, Redis, the API (uvicorn) and a served frontend, then runs this
// config against them.
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:5173";

// Allure results feed the report published to GitHub Pages for audit and
// trend tracking (FINTRACK-65). Written OUTSIDE apps/web so the API suite's
// results and this one land side by side under the repo-root allure-results/
// and merge into a single report per run.
const ALLURE_RESULTS_DIR =
  process.env.ALLURE_RESULTS_DIR ?? "../../allure-results/e2e";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: [
    // `line` rather than `html`: the HTML reporter opens a browser on failure
    // and blocks a CI runner forever. Allure is the durable report now.
    ["line"],
    ["junit", { outputFile: "../../e2e-results.xml" }],
    ["allure-playwright", { resultsDir: ALLURE_RESULTS_DIR }],
  ],
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  // Serves the production build the same way Hostinger will. Skipped when
  // E2E_SKIP_WEBSERVER is set, so CI can point at a stack it started itself.
  webServer: process.env.E2E_SKIP_WEBSERVER
    ? undefined
    : {
        command: "npm run preview -- --port 5173 --strictPort",
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
