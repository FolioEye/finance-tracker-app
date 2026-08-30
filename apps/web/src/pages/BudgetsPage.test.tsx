import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserRouter } from "react-router-dom";

import * as budgetsApi from "../api/budgets";
import { queryClient } from "../lib/queryClient";
import { BudgetsPage } from "./BudgetsPage";

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (state: { accessToken: string }) => unknown) =>
    selector({ accessToken: "test-token" }),
}));

function makeItem(overrides: Partial<budgetsApi.BudgetOverviewItem> = {}): budgetsApi.BudgetOverviewItem {
  return {
    budget_id: "budget-1",
    category: "Groceries",
    monthly_limit: "500.00",
    spent: "125.00",
    percent_used: "25",
    is_over_budget: false,
    ...overrides,
  };
}

function renderBudgetsPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <BudgetsPage />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

function mockMutation(overrides: Record<string, unknown> = {}) {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
    ...overrides,
  } as unknown;
}

describe("BudgetsPage (FINTRACK-55)", () => {
  beforeEach(() => {
    queryClient.clear();
    vi.spyOn(budgetsApi, "useCreateBudget").mockReturnValue(
      mockMutation() as ReturnType<typeof budgetsApi.useCreateBudget>,
    );
    vi.spyOn(budgetsApi, "useUpdateBudget").mockReturnValue(
      mockMutation() as ReturnType<typeof budgetsApi.useUpdateBudget>,
    );
    vi.spyOn(budgetsApi, "useDeleteBudget").mockReturnValue(
      mockMutation() as ReturnType<typeof budgetsApi.useDeleteBudget>,
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("happy path: setting a budget for a category submits the new limit", async () => {
    const user = userEvent.setup();
    const createBudgetMutate = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(budgetsApi, "useCreateBudget").mockReturnValue(
      mockMutation({ mutateAsync: createBudgetMutate }) as ReturnType<typeof budgetsApi.useCreateBudget>,
    );
    vi.spyOn(budgetsApi, "useBudgetOverview").mockReturnValue({
      data: { items: [makeItem({ budget_id: null, monthly_limit: null, percent_used: null })] },
      isLoading: false,
    } as unknown as ReturnType<typeof budgetsApi.useBudgetOverview>);

    renderBudgetsPage();

    await user.click(screen.getByTestId("set-budget-Groceries"));
    await user.type(screen.getByLabelText("Monthly limit for Groceries"), "300.00");
    await user.click(screen.getByTestId("save-new-budget-Groceries"));

    expect(createBudgetMutate).toHaveBeenCalledWith({ category: "Groceries", monthly_limit: "300.00" });
  });

  it("negative path: a non-positive budget limit is rejected client-side", async () => {
    const user = userEvent.setup();
    const createBudgetMutate = vi.fn();
    vi.spyOn(budgetsApi, "useCreateBudget").mockReturnValue(
      mockMutation({ mutateAsync: createBudgetMutate }) as ReturnType<typeof budgetsApi.useCreateBudget>,
    );
    vi.spyOn(budgetsApi, "useBudgetOverview").mockReturnValue({
      data: { items: [makeItem({ budget_id: null, monthly_limit: null, percent_used: null })] },
      isLoading: false,
    } as unknown as ReturnType<typeof budgetsApi.useBudgetOverview>);

    renderBudgetsPage();

    await user.click(screen.getByTestId("set-budget-Groceries"));
    await user.type(screen.getByLabelText("Monthly limit for Groceries"), "-50");
    await user.click(screen.getByTestId("save-new-budget-Groceries"));

    expect(screen.getByText("Budget must be a positive amount.")).toBeInTheDocument();
    expect(createBudgetMutate).not.toHaveBeenCalled();
  });

  it("edge case: zero budgets shows the empty state", () => {
    vi.spyOn(budgetsApi, "useBudgetOverview").mockReturnValue({
      data: { items: [] },
      isLoading: false,
    } as unknown as ReturnType<typeof budgetsApi.useBudgetOverview>);

    renderBudgetsPage();

    expect(screen.getByTestId("budgets-empty-state")).toBeInTheDocument();
  });

  it("shows true over-budget percentage uncapped (e.g. 125%), not clamped at 100", () => {
    vi.spyOn(budgetsApi, "useBudgetOverview").mockReturnValue({
      data: { items: [makeItem({ percent_used: "125", is_over_budget: true })] },
      isLoading: false,
    } as unknown as ReturnType<typeof budgetsApi.useBudgetOverview>);

    renderBudgetsPage();

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "125");
  });
});
