import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import { queryClient } from "../lib/queryClient";

import { ApiError } from "../api/client";
import * as importsApi from "../api/imports";
import { ImportReviewPage } from "./ImportReviewPage";

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

function makeCsvFile(name = "statement.csv") {
  return new File(["date,amount,category\n2026-08-01,10.00,Groceries"], name, { type: "text/csv" });
}

describe("ImportReviewPage (FINTRACK-54)", () => {
  beforeEach(() => {
    vi.spyOn(importsApi, "useUpdateStagedRows").mockReturnValue(
      mockMutation() as ReturnType<typeof importsApi.useUpdateStagedRows>,
    );
    vi.spyOn(importsApi, "useCommitImport").mockReturnValue(
      mockMutation() as ReturnType<typeof importsApi.useCommitImport>,
    );
    vi.spyOn(importsApi, "useDiscardImport").mockReturnValue(
      mockMutation() as ReturnType<typeof importsApi.useDiscardImport>,
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("happy path: staging a file shows the reviewed rows, and committing shows a confirmation", async () => {
    const user = userEvent.setup();
    const staged: importsApi.StagedImport = {
      import_id: "import-1",
      found_count: 1,
      flagged_count: 0,
      invalid_count: 0,
      auto_categorised_count: 1,
      needs_review_count: 0,
      rows: [
        {
          row_index: 0,
          raw_date: "2026-08-01",
          raw_amount: "10.00",
          category: "Groceries",
          note: null,
          status: "ok",
          warning: null,
          matched_rule_id: null,
        },
      ],
    };
    const stageImportMutate = vi.fn().mockResolvedValue(staged);
    vi.spyOn(importsApi, "useStageImport").mockReturnValue(
      mockMutation({ mutateAsync: stageImportMutate }) as ReturnType<typeof importsApi.useStageImport>,
    );
    const commitImportMutate = vi
      .fn()
      .mockResolvedValue({ committed_count: 1, skipped_count: 0 });
    vi.spyOn(importsApi, "useCommitImport").mockReturnValue(
      mockMutation({ mutateAsync: commitImportMutate }) as ReturnType<typeof importsApi.useCommitImport>,
    );

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ImportReviewPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    const file = makeCsvFile();
    const input = screen.getByTestId("import-file-input") as HTMLInputElement;
    await user.upload(input, file);

    expect(await screen.findByTestId("import-rows-table")).toBeInTheDocument();

    await user.click(screen.getByTestId("import-commit-button"));

    expect(commitImportMutate).toHaveBeenCalledWith("import-1");
    expect(await screen.findByTestId("import-commit-result")).toHaveTextContent(
      "Imported 1 transaction.",
    );
  });

  it("negative path: a corrupted/unparseable file surfaces a clear inline error", async () => {
    const user = userEvent.setup();
    const stageImportMutate = vi
      .fn()
      .mockRejectedValue(new ApiError(422, "This file could not be parsed as a CSV statement."));
    vi.spyOn(importsApi, "useStageImport").mockReturnValue(
      mockMutation({ mutateAsync: stageImportMutate }) as ReturnType<typeof importsApi.useStageImport>,
    );

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ImportReviewPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    const file = makeCsvFile("corrupted.csv");
    const input = screen.getByTestId("import-file-input") as HTMLInputElement;
    await user.upload(input, file);

    expect(await screen.findByTestId("import-upload-error")).toHaveTextContent(
      "This file could not be parsed as a CSV statement.",
    );
  });

  it("edge case: a file with a header row but zero data rows is handled gracefully", async () => {
    const user = userEvent.setup();
    const staged: importsApi.StagedImport = {
      import_id: "import-2",
      found_count: 0,
      flagged_count: 0,
      invalid_count: 0,
      auto_categorised_count: 0,
      needs_review_count: 0,
      rows: [],
    };
    const stageImportMutate = vi.fn().mockResolvedValue(staged);
    vi.spyOn(importsApi, "useStageImport").mockReturnValue(
      mockMutation({ mutateAsync: stageImportMutate }) as ReturnType<typeof importsApi.useStageImport>,
    );

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ImportReviewPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    const file = makeCsvFile("empty.csv");
    const input = screen.getByTestId("import-file-input") as HTMLInputElement;
    await user.upload(input, file);

    expect(await screen.findByTestId("import-zero-rows")).toHaveTextContent(
      "This file had a header row but no data rows.",
    );
  });

  it("lets the user discard a staged import", async () => {
    const user = userEvent.setup();
    const staged: importsApi.StagedImport = {
      import_id: "import-3",
      found_count: 1,
      flagged_count: 0,
      invalid_count: 0,
      auto_categorised_count: 1,
      needs_review_count: 0,
      rows: [
        {
          row_index: 0,
          raw_date: "2026-08-01",
          raw_amount: "10.00",
          category: "Groceries",
          note: null,
          status: "ok",
          warning: null,
          matched_rule_id: null,
        },
      ],
    };
    const stageImportMutate = vi.fn().mockResolvedValue(staged);
    vi.spyOn(importsApi, "useStageImport").mockReturnValue(
      mockMutation({ mutateAsync: stageImportMutate }) as ReturnType<typeof importsApi.useStageImport>,
    );
    const discardMutate = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(importsApi, "useDiscardImport").mockReturnValue(
      mockMutation({ mutateAsync: discardMutate }) as ReturnType<typeof importsApi.useDiscardImport>,
    );

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ImportReviewPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    await user.upload(screen.getByTestId("import-file-input"), makeCsvFile());
    await screen.findByTestId("import-rows-table");
    await user.click(screen.getByTestId("import-discard-button"));

    expect(discardMutate).toHaveBeenCalledWith("import-3");
  });
});
