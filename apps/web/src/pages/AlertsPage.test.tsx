import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserRouter } from "react-router-dom";

import * as alertsApi from "../api/alerts";
import { queryClient } from "../lib/queryClient";
import { AlertsPage } from "./AlertsPage";

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (state: { accessToken: string }) => unknown) =>
    selector({ accessToken: "test-token" }),
}));

function makeAlert(overrides: Partial<alertsApi.Alert> = {}): alertsApi.Alert {
  return {
    id: "alert-1",
    category: "Groceries",
    alert_type: "BUDGET_RISK",
    period_start: "2026-08-01",
    threshold_pct: "90",
    transaction_id: null,
    fired_at: "2026-08-15T00:00:00Z",
    dismissed_at: null,
    ...overrides,
  };
}

function renderAlertsPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AlertsPage />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

describe("AlertsPage (FINTRACK-57)", () => {
  beforeEach(() => {
    queryClient.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("happy path: dismissing an alert removes it from the unread list", async () => {
    const user = userEvent.setup();
    const alert = makeAlert();
    const mutateSpy = vi.fn();

    vi.spyOn(alertsApi, "useAlerts").mockReturnValue({
      data: { items: [alert] },
      isLoading: false,
    } as unknown as ReturnType<typeof alertsApi.useAlerts>);

    vi.spyOn(alertsApi, "useDismissAlert").mockReturnValue({
      mutate: mutateSpy,
      isPending: false,
      isError: false,
    } as unknown as ReturnType<typeof alertsApi.useDismissAlert>);

    renderAlertsPage();

    expect(screen.getByTestId("alert-row-alert-1")).toBeInTheDocument();
    await user.click(screen.getByTestId("dismiss-alert-alert-1"));

    expect(mutateSpy).toHaveBeenCalledWith("alert-1");
  });

  it("negative path: a failed dismiss keeps the alert visible with an inline retry option", () => {
    const alert = makeAlert();

    vi.spyOn(alertsApi, "useAlerts").mockReturnValue({
      data: { items: [alert] },
      isLoading: false,
    } as unknown as ReturnType<typeof alertsApi.useAlerts>);

    vi.spyOn(alertsApi, "useDismissAlert").mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: true,
    } as unknown as ReturnType<typeof alertsApi.useDismissAlert>);

    renderAlertsPage();

    // The alert must still be on screen -- a 500 must never optimistically
    // remove it while it's still active server-side.
    expect(screen.getByTestId("alert-row-alert-1")).toBeInTheDocument();
    expect(screen.getByTestId("retry-dismiss-alert-1")).toBeInTheDocument();
  });

  it("edge case: zero alerts shows the empty state and no nav badge count", () => {
    vi.spyOn(alertsApi, "useAlerts").mockReturnValue({
      data: { items: [] },
      isLoading: false,
    } as unknown as ReturnType<typeof alertsApi.useAlerts>);

    renderAlertsPage();

    expect(screen.getByTestId("alerts-empty-state")).toBeInTheDocument();
    expect(screen.getByText("No alerts right now")).toBeInTheDocument();
    expect(screen.queryByTestId("alerts-nav-badge")).not.toBeInTheDocument();
  });

  it("shows a loading state while alerts are being fetched", () => {
    vi.spyOn(alertsApi, "useAlerts").mockReturnValue({
      data: undefined,
      isLoading: true,
    } as unknown as ReturnType<typeof alertsApi.useAlerts>);

    renderAlertsPage();

    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
