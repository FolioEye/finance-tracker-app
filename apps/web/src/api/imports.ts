import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useAuthStore } from "../store/authStore";
import { apiRequest } from "./client";

export interface StagedRow {
  row_index: number;
  raw_date: string;
  raw_amount: string;
  category: string;
  note: string | null;
  status: string;
  warning: string | null;
  matched_rule_id: string | null;
}

export interface StagedImport {
  import_id: string;
  found_count: number;
  flagged_count: number;
  invalid_count: number;
  auto_categorised_count: number;
  needs_review_count: number;
  rows: StagedRow[];
}

export interface RowEdit {
  row_index: number;
  raw_date?: string;
  raw_amount?: string;
  category?: string;
  note?: string;
}

interface CommitImportResponse {
  committed_count: number;
  skipped_count: number;
}

export function useStageImport() {
  const accessToken = useAuthStore((state) => state.accessToken);
  return useMutation({
    mutationFn: (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return apiRequest<StagedImport>("/api/v1/imports", {
        method: "POST",
        body: formData,
        accessToken,
      });
    },
  });
}

export function useUpdateStagedRows() {
  const accessToken = useAuthStore((state) => state.accessToken);
  return useMutation({
    mutationFn: ({ importId, edits }: { importId: string; edits: RowEdit[] }) =>
      apiRequest<StagedImport>(`/api/v1/imports/${importId}`, {
        method: "PATCH",
        body: { edits },
        accessToken,
      }),
  });
}

export function useCommitImport() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (importId: string) =>
      apiRequest<CommitImportResponse>(`/api/v1/imports/${importId}/commit`, {
        method: "POST",
        accessToken,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["budgets"] });
      queryClient.invalidateQueries({ queryKey: ["insights"] });
      queryClient.invalidateQueries({ queryKey: ["recommendations"] });
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
  });
}

export function useDiscardImport() {
  const accessToken = useAuthStore((state) => state.accessToken);
  return useMutation({
    mutationFn: (importId: string) =>
      apiRequest<void>(`/api/v1/imports/${importId}`, { method: "DELETE", accessToken }),
  });
}
