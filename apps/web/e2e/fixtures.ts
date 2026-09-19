import { test as base, type Page } from "@playwright/test";

const TEST_SESSION = {
  accessToken: "e2e-test-access-token",
  userId: "e2e-user-1",
  email: "e2e@example.com",
};

// Shared helper for every FINTRACK-51 batch spec. Auth is seeded directly
// rather than driven through the UI: a real Google OAuth popup isn't
// automatable, and every one of these journeys starts from "already logged in"
// per its own Gherkin (auth itself is FINTRACK-38's story, tested separately).
//
// FINTRACK-66 -- why addInitScript rather than page.evaluate:
//
// This used to goto("/login"), wait for __E2E_AUTH_STORE__, and call
// setSession once. That seeded a store which the spec's very next line --
// page.goto("/alerts") and friends -- immediately destroyed. page.goto is a
// real document navigation, and the access token lives in memory only by
// design (store/authStore.ts: no persist middleware, "never
// localStorage/sessionStorage"). So every protected-route spec arrived
// unauthenticated, ProtectedRoute redirected to /login, and the assertions
// failed with "element(s) not found" on testids that were never going to be
// on a login page. Confirmed on run 93986631831: 3 of 5 specs, all this.
//
// addInitScript is evaluated before page scripts on EVERY document load for
// the life of the page, so the session is present when main.tsx runs, on the
// first navigation and on every one after it. The app's in-memory design is
// untouched -- nothing is persisted to browser storage.
//
// Call this BEFORE the spec's first navigation; it no longer navigates itself.
export async function loginAsTestUser(page: Page) {
  await page.addInitScript((session) => {
    (window as unknown as { __E2E_SESSION__: typeof session }).__E2E_SESSION__ = session;
  }, TEST_SESSION);
}

// Still exported: specs that need to change the session mid-test (e.g. clear
// it to assert a redirect) reach the live store through this.
export const test = base;
export { expect } from "@playwright/test";
