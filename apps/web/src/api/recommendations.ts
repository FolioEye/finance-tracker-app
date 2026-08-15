import { useQuery } from "@tanstack/react-query";

import { useAuthStore } from "../store/authStore";
import { apiRequest } from "./client";

export type RecommendationType =
  | "BUDGET_RISK"
  | "SPENDING_SPIKE"
  | "NEW_SUBSCRIPTION"
  | "NEUTRAL";

export interface WeeklyRecommendation {
  type: RecommendationType;
  message: string;
  category: string | null;
  merchant: string | null;
  follow_through_record_id: string;
  deprioritization_reason: string | null;
}

export function useWeeklyRecommendation() {
  const accessToken = useAuthStore((state) => state.accessToken);
  return useQuery({
    queryKey: ["recommendations", "weekly"],
    queryFn: () =>
      apiRequest<WeeklyRecommendation>("/api/v1/recommendations/weekly", { accessToken }),
    // A failed recommendation fetch must never take the rest of the
    // dashboard down with it (FINTRACK-52 AC2/FINTRACK-58 AC2) -- callers
    // read `.isError` and render an inline fallback instead of throwing,
    // so this stays a plain default-retry query, not `throwOnError`.
  });
}
