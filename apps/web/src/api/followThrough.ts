import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useAuthStore } from "../store/authStore";
import { apiRequest } from "./client";

export type FollowThroughAction = "done" | "dismiss" | "ignore";

export function useRecordFollowThroughAction() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ recordId, action }: { recordId: string; action: FollowThroughAction }) =>
      apiRequest<void>(`/api/v1/follow-through/${recordId}/actions`, {
        method: "POST",
        body: { action },
        accessToken,
      }),
    onSuccess: () => {
      // FINTRACK-58 AC4: the recommendation card must update without a
      // manual refresh once the user acts on it.
      queryClient.invalidateQueries({ queryKey: ["recommendations"] });
    },
  });
}
