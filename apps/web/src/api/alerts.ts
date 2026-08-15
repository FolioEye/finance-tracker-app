import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuthStore } from "../store/authStore";
import { apiRequest } from "./client";

export interface Alert {
  id: string;
  category: string;
  alert_type: string;
  period_start: string;
  threshold_pct: string | null;
  transaction_id: string | null;
  fired_at: string;
  dismissed_at: string | null;
}

interface AlertListResponse {
  items: Alert[];
}

export function useAlerts(includeDismissed = false) {
  const accessToken = useAuthStore((state) => state.accessToken);
  return useQuery({
    queryKey: ["alerts", includeDismissed],
    queryFn: () =>
      apiRequest<AlertListResponse>(
        `/api/v1/alerts?include_dismissed=${includeDismissed}`,
        { accessToken },
      ),
  });
}

export function useDismissAlert() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (alertId: string) =>
      apiRequest<void>(`/api/v1/alerts/${alertId}/dismiss`, { method: "POST", accessToken }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });
}
