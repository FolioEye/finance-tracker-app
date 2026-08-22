import { test as base, type Page } from "@playwright/test";

// Shared helpers for every FINTRACK-51 batch spec. Auth is seeded directly
// into the Zustand store via the VITE_E2E_TEST_MODE seam (see main.tsx) --
// driving a real Google OAuth popup isn't automatable, and every one of
// these journeys starts from "already logged in" per its own Gherkin
// (auth itself is FINTRACK-38's story, tested separately).
export async function loginAsTestUser(page: Page) {
  await page.goto("/login");
  await page.waitForFunction(() => Boolean((window as any).__E2E_AUTH_STORE__));
  await page.evaluate(() => {
    (window as any).__E2E_AUTH_STORE__.getState().setSession({
      accessToken: "e2e-test-access-token",
      userId: "e2e-user-1",
      email: "e2e@example.com",
    });
  });
}

export const test = base;
export { expect } from "@playwright/test";
