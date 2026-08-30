import { expect, test } from "@playwright/test";

import { loginAsTestUser } from "./fixtures";

// FINTRACK-55 critical journey: set a monthly limit for a category and see
// the budget-health progress bar reflect it immediately.
test("setting a budget for a category shows its progress bar", async ({ page }) => {
  let budgetSet = false;

  await page.route("**/api/v1/budgets*", async (route) => {
    if (route.request().method() === "POST") {
      budgetSet = true;
      await route.fulfill({
        json: {
          id: "budget-e2e-1",
          category: "Groceries",
          monthly_limit: "300.00",
          created_at: "2026-08-20T00:00:00Z",
          updated_at: "2026-08-20T00:00:00Z",
        },
      });
      return;
    }
    await route.fulfill({
      json: {
        items: [
          {
            budget_id: budgetSet ? "budget-e2e-1" : null,
            category: "Groceries",
            monthly_limit: budgetSet ? "300.00" : null,
            spent: "75.00",
            percent_used: budgetSet ? "25" : null,
            is_over_budget: false,
          },
        ],
      },
    });
  });

  await loginAsTestUser(page);
  await page.goto("/budgets");

  await page.getByTestId("set-budget-Groceries").click();
  await page.getByLabel("Monthly limit for Groceries").fill("300.00");
  await page.getByTestId("save-new-budget-Groceries").click();

  await expect(page.getByRole("progressbar", { name: "Groceries budget usage" })).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "Groceries budget usage" })).toHaveAttribute(
    "aria-valuenow",
    "25",
  );
});
