import { expect, test } from "@playwright/test";

// FINTRACK-52/57/58 shared security scenario: unauthenticated access to
// any protected route redirects to /login with no protected content ever
// rendered (no flash of real data before the redirect).
test.describe("Unauthenticated access (security)", () => {
  test("visiting a protected route while logged out redirects to /login", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText("Sign in to FinTrack")).toBeVisible();
  });

  test("visiting /alerts while logged out redirects to /login, never showing alert content", async ({
    page,
  }) => {
    await page.goto("/alerts");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByTestId("alerts-list")).toHaveCount(0);
  });
});
