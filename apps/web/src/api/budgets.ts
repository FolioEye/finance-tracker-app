import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuthStore } from "../store/authStore";
import { apiRequest } from "./client";

export interface BudgetOverviewItem {
  budget_id: string | null;
  category: string;
  monthly_limit: string | null;
  spent: string;
  percent_used: string | null;
  is_over_budget: boolean;
}

interface BudgetOverviewResponse {
  items: BudgetOverviewItem[];
}

export interface Budget {
  id: string;
  category: string;
  monthly_limit: string;
  created_at: string;
  updated_at: string;
}

function invalidateBudgetQueries(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["budgets"] });
  queryClient.invalidateQueries({ queryKey: ["insights"] });
  queryClient.invalidateQueries({ queryKey: ["recommendations"] });
}

export function useBudgetOverview() {
  const accessToken = useAuthStore((state) => state.accessToken);
  return useQuery({
    queryKey: ["budgets", "overview"],
    queryFn: () => apiRequest<BudgetOverviewResponse>("/api/v1/budgets", { accessToken }),
  });
}

export function useCreateBudget() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { category: string; monthly_limit: string }) =>
      apiRequest<Budget>("/api/v1/budgets", { method: "POST", body: input, accessToken }),
    onSuccess: () => invalidateBudgetQueries(queryClient),
  });
}

export function useUpdateBudget() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, monthly_limit }: { id: string; monthly_limit: string }) =>
      apiRequest<Budget>(`/api/v1/budgets/${id}`, {
        method: "PATCH",
        body: { monthly_limit },
        accessToken,
      }),
    onSuccess: () => invalidateBudgetQueries(queryClient),
  });
}

export function useDeleteBudget() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest<void>(`/api/v1/budgets/${id}`, { method: "DELETE", accessToken }),
    onSuccess: () => invalidateBudgetQueries(queryClient),
  });
}
