import { expect, test } from "@playwright/test";

import { loginAsTestUser } from "./fixtures";

// FINTRACK-53 critical journey: add a transaction end-to-end and see it
// land in the list. Validation/XSS/empty-state edge cases are covered at
// the component layer (vitest); this is the one real-browser, real-form,
// real-navigation path worth the E2E cost.
test("adding a transaction shows it in the list", async ({ page }) => {
  let created = false;
  const transaction = {
    id: "tx-e2e-1",
    amount: "42.50",
    category: "Groceries",
    transaction_date: "2026-08-20",
    note: "Weekly shop",
    entry_source: "manual",
  };

  await page.route("**/api/v1/transactions*", async (route) => {
    if (route.request().method() === "POST") {
      created = true;
      await route.fulfill({ json: transaction });
      return;
    }
    await route.fulfill({ json: { items: created ? [transaction] : [], next_cursor: null } });
  });

  await loginAsTestUser(page);
  await page.goto("/transactions");

  await expect(page.getByTestId("transactions-empty-state")).toBeVisible();

  await page.getByTestId("add-transaction-button").click();
  await page.getByLabel("Amount").fill("42.50");
  await page.getByLabel("Category").fill("Groceries");
  await page.getByLabel("Note (optional)").fill("Weekly shop");
  await page.getByTestId("submit-transaction-form").click();

  await expect(page.getByTestId(`transaction-row-${transaction.id}`)).toBeVisible();
  await expect(page.getByTestId(`transaction-row-${transaction.id}`)).toContainText("Weekly shop");
});
