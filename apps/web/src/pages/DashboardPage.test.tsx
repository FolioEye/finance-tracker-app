import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrowserRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as budgetsApi from "../api/budgets";
import * as followThroughApi from "../api/followThrough";
import * as insightsApi from "../api/insights";
import * as recommendationsApi from "../api/recommendations";
import { queryClient } from "../lib/queryClient";
import { DashboardPage } from "./DashboardPage";

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (state: { accessToken: string }) => unknown) =>
    selector({ accessToken: "test-token" }),
}));
vi.mock("../api/alerts", () => ({
  useAlerts: () => ({ data: { items: [] }, isLoading: false }),
}));

function renderDashboard() {
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <DashboardPage />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

const NON_EMPTY_INSIGHTS = {
  current_month_total: "500.00",
  by_category: [{ category: "Groceries", total: "500.00" }],
  monthly_trend: [],
};
const NON_EMPTY_BUDGETS = {
  items: [
    {
      budget_id: "b1",
      category: "Groceries",
      monthly_limit: "600",
      spent: "500.00",
      percent_used: "83.3",
      is_over_budget: false,
    },
  ],
};

describe("DashboardPage shell (FINTRACK-52)", () => {
  beforeEach(() => {
    queryClient.clear();
    vi.spyOn(insightsApi, "useSpendingInsights").mockReturnValue({
      data: NON_EMPTY_INSIGHTS,
      isLoading: false,
    } as unknown as ReturnType<typeof insightsApi.useSpendingInsights>);
    vi.spyOn(budgetsApi, "useBudgetOverview").mockReturnValue({
      data: NON_EMPTY_BUDGETS,
      isLoading: false,
    } as unknown as ReturnType<typeof budgetsApi.useBudgetOverview>);
    vi.spyOn(recommendationsApi, "useWeeklyRecommendation").mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    } as unknown as ReturnType<typeof recommendationsApi.useWeeklyRecommendation>);
    vi.spyOn(followThroughApi, "useRecordFollowThroughAction").mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof followThroughApi.useRecordFollowThroughAction>);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("edge case: a brand-new user with no transactions or budgets sees a welcome empty state", () => {
    vi.spyOn(insightsApi, "useSpendingInsights").mockReturnValue({
      data: { current_month_total: "0", by_category: [], monthly_trend: [] },
      isLoading: false,
    } as unknown as ReturnType<typeof insightsApi.useSpendingInsights>);
    vi.spyOn(budgetsApi, "useBudgetOverview").mockReturnValue({
      data: { items: [] },
      isLoading: false,
    } as unknown as ReturnType<typeof budgetsApi.useBudgetOverview>);

    renderDashboard();

    expect(screen.getByTestId("dashboard-empty-state")).toBeInTheDocument();
    expect(screen.getByText("Welcome to FinTrack")).toBeInTheDocument();
  });

  it("renders the persistent nav alongside page content for a returning user", () => {
    renderDashboard();

    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });
});

// FINTRACK-58's security scenario (marking another user's recommendation
// done via a guessed/forged follow_through_record_id must 403/404, no
// cross-user leak) is an authorization boundary enforced by the backend
// endpoint (POST /api/v1/follow-through/{recordId}/actions), not something
// this component layer can meaningfully assert -- the UI only ever passes
// through whatever record_id its own query returned. Covered by the
// backend's own security test suite (tests/security/), not duplicated here.
describe("Weekly recommendation card (FINTRACK-58)", () => {
  beforeEach(() => {
    queryClient.clear();
    vi.spyOn(insightsApi, "useSpendingInsights").mockReturnValue({
      data: NON_EMPTY_INSIGHTS,
      isLoading: false,
    } as unknown as ReturnType<typeof insightsApi.useSpendingInsights>);
    vi.spyOn(budgetsApi, "useBudgetOverview").mockReturnValue({
      data: NON_EMPTY_BUDGETS,
      isLoading: false,
    } as unknown as ReturnType<typeof budgetsApi.useBudgetOverview>);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("happy path: viewing a BUDGET_RISK recommendation and marking it done invokes the follow-through action", async () => {
    const user = userEvent.setup();
    vi.spyOn(recommendationsApi, "useWeeklyRecommendation").mockReturnValue({
      data: {
        type: "BUDGET_RISK",
        message: "Groceries is at 92% of its budget with 9 days left in the month.",
        category: "Groceries",
        merchant: null,
        follow_through_record_id: "rec-1",
        deprioritization_reason: null,
      },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof recommendationsApi.useWeeklyRecommendation>);
    const recordMutate = vi.fn();
    vi.spyOn(followThroughApi, "useRecordFollowThroughAction").mockReturnValue({
      mutate: recordMutate,
      isPending: false,
    } as unknown as ReturnType<typeof followThroughApi.useRecordFollowThroughAction>);

    renderDashboard();

    expect(screen.getByText("Groceries is at 92% of its budget with 9 days left in the month.")).toBeInTheDocument();
    await user.click(screen.getByTestId("recommendation-mark-done"));

    expect(recordMutate).toHaveBeenCalledWith({ recordId: "rec-1", action: "done" });
  });

  it("negative path: a failed recommendation fetch shows an inline message without breaking the rest of the dashboard", () => {
    vi.spyOn(recommendationsApi, "useWeeklyRecommendation").mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    } as unknown as ReturnType<typeof recommendationsApi.useWeeklyRecommendation>);

    renderDashboard();

    expect(screen.getByTestId("recommendation-error")).toHaveTextContent(
      "Couldn't load this week's recommendation.",
    );
    // The rest of the dashboard (spend summary, budgets) still renders.
    expect(screen.getByText("This month's spend")).toBeInTheDocument();
  });

  it("edge case: no qualifying recommendation shows a graceful neutral state, not an empty/broken card", () => {
    vi.spyOn(recommendationsApi, "useWeeklyRecommendation").mockReturnValue({
      data: {
        type: "NEUTRAL",
        message: "",
        category: null,
        merchant: null,
        follow_through_record_id: "rec-2",
        deprioritization_reason: null,
      },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof recommendationsApi.useWeeklyRecommendation>);

    renderDashboard();

    expect(screen.getByText("You're on track this week")).toBeInTheDocument();
    expect(screen.queryByTestId("recommendation-mark-done")).not.toBeInTheDocument();
  });

  it("shows a loading state while the recommendation is being computed", () => {
    vi.spyOn(recommendationsApi, "useWeeklyRecommendation").mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    } as unknown as ReturnType<typeof recommendationsApi.useWeeklyRecommendation>);

    renderDashboard();

    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
