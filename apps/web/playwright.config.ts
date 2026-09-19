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
// Postgres, Redis and the API (uvicorn); this config starts the frontend.
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:5173";
const API_URL = process.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// Allure results feed the report published to GitHub Pages for audit and
// trend tracking (FINTRACK-65). Written OUTSIDE apps/web so the API suite's
// results and this one land side by side under the repo-root allure-results/
// and merge into a single report per run.
//
// FINTRACK-68: the option below is `outputFolder`, NOT `resultsDir`.
// `resultsDir` is the allure-playwright 3.x name; this repo pins the 2.x line
// (2.15.1) to match the Allure 2 format allure-commandline generates. 2.x
// takes { detail, outputFolder, suiteTitle, categories, environmentInfo } and
// SILENTLY IGNORES anything else, then falls back to
// path.resolve(process.cwd(), "allure-results") -- so the misspelled key sent
// every result to apps/web/allure-results/, the upload step matched nothing,
// and the published report contained zero tests on a green pipeline. There is
// no error for getting this name wrong; only an empty report.
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
    ["allure-playwright", { outputFolder: ALLURE_RESULTS_DIR }],
  ],
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  // `npm run dev`, NOT `npm run build` + `vite preview`.
  //
  // This is load-bearing and was got wrong once (run 93985092334: 3 of 5 specs
  // timed out for 30s each on fixtures.ts:10). main.tsx gates the E2E auth
  // seam on `!import.meta.env.PROD && VITE_E2E_TEST_MODE === "true"` -- the
  // PROD half being a deliberate second guard so the seam can never ship in a
  // production bundle. A `vite build` output therefore NEVER exposes
  // __E2E_AUTH_STORE__, and every spec that seeds auth through it hangs.
  //
  // The guard is right and stays. The server is what has to change: dev mode
  // has PROD false, so the seam attaches. This is the arrangement main.tsx
  // describes -- "Playwright's own webServer env, not a normal dev/build run".
  //
  // Consequence: this tier exercises the dev bundle, not the production
  // artifact. Production build integrity is covered by
  // tests/integration/test_frontend_build.py and the build-frontend job.
  //
  // env is set here rather than in the workflow so `npx playwright test`
  // stands up a correct server on its own, locally too, instead of depending
  // on a particular sequence of CI steps having run first.
  webServer: process.env.E2E_SKIP_WEBSERVER
    ? undefined
    : {
        command: "npm run dev -- --port 5173 --strictPort",
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        env: {
          VITE_E2E_TEST_MODE: "true",
          VITE_API_BASE_URL: API_URL,
        },
      },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
