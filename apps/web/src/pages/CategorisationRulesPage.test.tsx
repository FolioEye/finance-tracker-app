import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import { queryClient } from "../lib/queryClient";

import { ApiError } from "../api/client";
import * as rulesApi from "../api/categorisationRules";
import { CategorisationRulesPage } from "./CategorisationRulesPage";

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (state: { accessToken: string }) => unknown) =>
    selector({ accessToken: "test-token" }),
}));

function mockMutation(overrides: Record<string, unknown> = {}) {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
    ...overrides,
  } as unknown;
}

describe("CategorisationRulesPage (FINTRACK-56)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("happy path: creating a rule shows a confirmation banner", async () => {
    const user = userEvent.setup();
    const createMutate = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(rulesApi, "useCreateCategorisationRule").mockReturnValue(
      mockMutation({ mutateAsync: createMutate }) as ReturnType<
        typeof rulesApi.useCreateCategorisationRule
      >,
    );

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <CategorisationRulesPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    await user.type(screen.getByTestId("merchant-pattern-input"), "STARBUCKS");
    await user.type(screen.getByTestId("rule-category-input"), "Coffee & Dining");
    await user.click(screen.getByTestId("create-rule-submit"));

    expect(createMutate).toHaveBeenCalledWith({
      merchant_pattern: "STARBUCKS",
      category: "Coffee & Dining",
    });
    expect(await screen.findByTestId("rule-created-banner")).toHaveTextContent(
      'Future transactions matching "STARBUCKS" will be categorised as Coffee & Dining.',
    );
  });

  it("negative path: an empty merchant pattern is rejected client-side", async () => {
    const user = userEvent.setup();
    const createMutate = vi.fn();
    vi.spyOn(rulesApi, "useCreateCategorisationRule").mockReturnValue(
      mockMutation({ mutateAsync: createMutate }) as ReturnType<
        typeof rulesApi.useCreateCategorisationRule
      >,
    );

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <CategorisationRulesPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    await user.type(screen.getByTestId("rule-category-input"), "Coffee & Dining");
    await user.click(screen.getByTestId("create-rule-submit"));

    expect(screen.getByTestId("create-rule-error")).toHaveTextContent(
      "Merchant pattern is required.",
    );
    expect(createMutate).not.toHaveBeenCalled();
  });

  it("edge case: a duplicate/conflicting pattern surfaces the backend's error message", async () => {
    const user = userEvent.setup();
    const createMutate = vi
      .fn()
      .mockRejectedValue(new ApiError(409, "A rule for this merchant pattern already exists."));
    vi.spyOn(rulesApi, "useCreateCategorisationRule").mockReturnValue(
      mockMutation({ mutateAsync: createMutate }) as ReturnType<
        typeof rulesApi.useCreateCategorisationRule
      >,
    );

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <CategorisationRulesPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    await user.type(screen.getByTestId("merchant-pattern-input"), "STARBUCKS");
    await user.type(screen.getByTestId("rule-category-input"), "Coffee & Dining");
    await user.click(screen.getByTestId("create-rule-submit"));

    expect(await screen.findByTestId("create-rule-error")).toHaveTextContent(
      "A rule for this merchant pattern already exists.",
    );
  });

  it("security: a merchant pattern containing a SQL-injection-style payload is submitted verbatim as data, never interpolated", async () => {
    const user = userEvent.setup();
    const createMutate = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(rulesApi, "useCreateCategorisationRule").mockReturnValue(
      mockMutation({ mutateAsync: createMutate }) as ReturnType<
        typeof rulesApi.useCreateCategorisationRule
      >,
    );

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <CategorisationRulesPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    const payload = "'; DROP TABLE transactions; --";
    await user.type(screen.getByTestId("merchant-pattern-input"), payload);
    await user.type(screen.getByTestId("rule-category-input"), "Groceries");
    await user.click(screen.getByTestId("create-rule-submit"));

    // The frontend's only job is to pass this through as an opaque string
    // field in a JSON body (apiRequest always JSON.stringifies and never
    // builds a raw query) -- parameterisation is enforced server-side
    // (apps/api's repository layer), which is out of this test's scope.
    expect(createMutate).toHaveBeenCalledWith({ merchant_pattern: payload, category: "Groceries" });
  });
});
