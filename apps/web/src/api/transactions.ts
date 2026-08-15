import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuthStore } from "../store/authStore";
import { apiRequest } from "./client";

export interface Transaction {
  id: string;
  amount: string;
  category: string;
  transaction_date: string;
  note: string | null;
  entry_source: string;
}

interface TransactionListResponse {
  items: Transaction[];
  next_cursor: string | null;
}

export interface CreateTransactionInput {
  amount: string;
  category: string;
  transaction_date: string;
  note?: string | null;
}

export type UpdateTransactionInput = Partial<CreateTransactionInput>;

// Shared by every mutation below: a create/edit/delete anywhere in
// transactions can change budget spend, trigger new alerts, and change
// this week's recommendation -- so every one of those caches gets
// invalidated together rather than each mutation hand-picking a subset
// that's easy to get wrong and leave stale data on screen.
function invalidateMoneyDependentQueries(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["transactions"] });
  queryClient.invalidateQueries({ queryKey: ["budgets"] });
  queryClient.invalidateQueries({ queryKey: ["insights"] });
  queryClient.invalidateQueries({ queryKey: ["recommendations"] });
  queryClient.invalidateQueries({ queryKey: ["alerts"] });
}

export function useTransactions(params: { category?: string } = {}) {
  const accessToken = useAuthStore((state) => state.accessToken);
  return useQuery({
    queryKey: ["transactions", params],
    queryFn: async () => {
      const query = new URLSearchParams();
      query.set("limit", "200");
      const response = await apiRequest<TransactionListResponse>(
        `/api/v1/transactions?${query.toString()}`,
        { accessToken },
      );
      if (!params.category) {
        return response;
      }
      return {
        ...response,
        items: response.items.filter((t) => t.category === params.category),
      };
    },
  });
}

export function useCreateTransaction() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateTransactionInput) =>
      apiRequest<Transaction>("/api/v1/transactions", {
        method: "POST",
        body: input,
        accessToken,
      }),
    onSuccess: () => invalidateMoneyDependentQueries(queryClient),
  });
}

export function useUpdateTransaction() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: UpdateTransactionInput }) =>
      apiRequest<Transaction>(`/api/v1/transactions/${id}`, {
        method: "PATCH",
        body: input,
        accessToken,
      }),
    onSuccess: () => invalidateMoneyDependentQueries(queryClient),
  });
}

export function useDeleteTransaction() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest<void>(`/api/v1/transactions/${id}`, { method: "DELETE", accessToken }),
    onSuccess: () => invalidateMoneyDependentQueries(queryClient),
  });
}
