import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserRouter } from "react-router-dom";

import * as transactionsApi from "../api/transactions";
import { queryClient } from "../lib/queryClient";
import { TransactionsPage } from "./TransactionsPage";

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (state: { accessToken: string }) => unknown) =>
    selector({ accessToken: "test-token" }),
}));

function makeTx(overrides: Partial<transactionsApi.Transaction> = {}): transactionsApi.Transaction {
  return {
    id: "tx-1",
    amount: "42.50",
    category: "Groceries",
    transaction_date: "2026-08-10",
    note: "Weekly shop",
    entry_source: "manual",
    ...overrides,
  };
}

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <TransactionsPage />
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

describe("TransactionsPage (FINTRACK-53)", () => {
  beforeEach(() => {
    queryClient.clear();
    vi.spyOn(transactionsApi, "useCreateTransaction").mockReturnValue(
      mockMutation() as ReturnType<typeof transactionsApi.useCreateTransaction>,
    );
    vi.spyOn(transactionsApi, "useUpdateTransaction").mockReturnValue(
      mockMutation() as ReturnType<typeof transactionsApi.useUpdateTransaction>,
    );
    vi.spyOn(transactionsApi, "useDeleteTransaction").mockReturnValue(
      mockMutation() as ReturnType<typeof transactionsApi.useDeleteTransaction>,
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("happy path: adding a transaction submits the form values", async () => {
    const user = userEvent.setup();
    const createMutate = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(transactionsApi, "useCreateTransaction").mockReturnValue(
      mockMutation({ mutateAsync: createMutate }) as ReturnType<typeof transactionsApi.useCreateTransaction>,
    );
    vi.spyOn(transactionsApi, "useTransactions").mockReturnValue({
      data: { items: [], next_cursor: null },
      isLoading: false,
    } as unknown as ReturnType<typeof transactionsApi.useTransactions>);

    renderPage();

    await user.click(screen.getByTestId("add-transaction-button"));
    await user.type(screen.getByLabelText("Amount"), "42.50");
    await user.type(screen.getByLabelText("Category"), "Groceries");
    await user.click(screen.getByTestId("submit-transaction-form"));

    expect(createMutate).toHaveBeenCalledWith(
      expect.objectContaining({ amount: "42.50", category: "Groceries" }),
    );
  });

  it("negative path: a non-positive amount is rejected before any request is made", async () => {
    const user = userEvent.setup();
    const createMutate = vi.fn();
    vi.spyOn(transactionsApi, "useCreateTransaction").mockReturnValue(
      mockMutation({ mutateAsync: createMutate }) as ReturnType<typeof transactionsApi.useCreateTransaction>,
    );
    vi.spyOn(transactionsApi, "useTransactions").mockReturnValue({
      data: { items: [], next_cursor: null },
      isLoading: false,
    } as unknown as ReturnType<typeof transactionsApi.useTransactions>);

    renderPage();

    await user.click(screen.getByTestId("add-transaction-button"));
    await user.type(screen.getByLabelText("Amount"), "-5");
    await user.type(screen.getByLabelText("Category"), "Groceries");
    await user.click(screen.getByTestId("submit-transaction-form"));

    expect(screen.getByRole("alert")).toHaveTextContent("Amount must be a positive number.");
    expect(createMutate).not.toHaveBeenCalled();
  });

  it("edge case: zero transactions shows the empty state", () => {
    vi.spyOn(transactionsApi, "useTransactions").mockReturnValue({
      data: { items: [], next_cursor: null },
      isLoading: false,
    } as unknown as ReturnType<typeof transactionsApi.useTransactions>);

    renderPage();

    expect(screen.getByTestId("transactions-empty-state")).toBeInTheDocument();
  });

  it("security: a note containing a script tag renders as inert text, never as markup", () => {
    vi.spyOn(transactionsApi, "useTransactions").mockReturnValue({
      data: {
        items: [makeTx({ note: "<script>window.__xss = true;</script>" })],
        next_cursor: null,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof transactionsApi.useTransactions>);

    renderPage();

    expect(screen.getByText("<script>window.__xss = true;</script>")).toBeInTheDocument();
    expect(document.querySelector("script[src], script:not([type])")).not.toBeInTheDocument();
  });
});
