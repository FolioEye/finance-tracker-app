import { expect, test } from "@playwright/test";

import { loginAsTestUser } from "./fixtures";

const ALERT = {
  id: "alert-e2e-1",
  category: "Groceries",
  alert_type: "BUDGET_RISK",
  period_start: "2026-08-01",
  threshold_pct: "90",
  transaction_id: null,
  fired_at: "2026-08-15T00:00:00Z",
  dismissed_at: null,
};

// FINTRACK-57 critical journey: view an alert, dismiss it, see it drop off
// the list and the nav badge update -- the one E2E-tier flow for this
// story, everything else (retry-on-failure, empty state) is covered at
// the component/vitest layer already.
test("dismissing an alert removes it from the list and clears the nav badge", async ({ page }) => {
  let dismissed = false;

  await page.route("**/api/v1/alerts*", async (route) => {
    const items = dismissed ? [] : [ALERT];
    await route.fulfill({ json: { items } });
  });
  await page.route("**/api/v1/alerts/*/dismiss", async (route) => {
    dismissed = true;
    await route.fulfill({ status: 204, body: "" });
  });

  await loginAsTestUser(page);
  await page.goto("/alerts");

  await expect(page.getByTestId("alert-row-alert-e2e-1")).toBeVisible();
  await expect(page.getByTestId("alerts-nav-badge")).toHaveText("1");

  await page.getByTestId("dismiss-alert-alert-e2e-1").click();

  await expect(page.getByTestId("alerts-empty-state")).toBeVisible();
  await expect(page.getByTestId("alerts-nav-badge")).toHaveCount(0);
});
