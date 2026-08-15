import { useQuery } from "@tanstack/react-query";

import { useAuthStore } from "../store/authStore";
import { apiRequest } from "./client";

export interface CategoryBreakdownItem {
  category: string;
  total: string;
}

export interface MonthlyTrendItem {
  month: string;
  total: string;
}

export interface SpendingInsights {
  current_month_total: string;
  by_category: CategoryBreakdownItem[];
  monthly_trend: MonthlyTrendItem[];
}

export function useSpendingInsights(trendMonths = 6) {
  const accessToken = useAuthStore((state) => state.accessToken);
  return useQuery({
    queryKey: ["insights", "dashboard", trendMonths],
    queryFn: () =>
      apiRequest<SpendingInsights>(
        `/api/v1/insights/dashboard?trend_months=${trendMonths}`,
        { accessToken },
      ),
  });
}
