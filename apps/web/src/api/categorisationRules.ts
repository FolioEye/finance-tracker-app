import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useAuthStore } from "../store/authStore";
import { apiRequest } from "./client";

export interface CategorisationRule {
  id: string;
  merchant_pattern: string;
  category: string;
  created_at: string;
  updated_at: string;
}

// FINTRACK-56 scope note: the backend (apps/api/presentation/api/v1/
// categorisation_rules.py) only exposes POST -- there is no list/delete
// endpoint yet (see that file's own docstring: "no Gherkin-tested
// requirement for listing/deleting rules yet", ADR-012). So this client
// only wraps creation; the "rules list" and "needs-review queue" parts of
// FINTRACK-56's original acceptance criteria are flagged as a backend gap
// in the Tech Lead envelope rather than built against endpoints that
// don't exist.
export function useCreateCategorisationRule() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { merchant_pattern: string; category: string }) =>
      apiRequest<CategorisationRule>("/api/v1/categorisation-rules", {
        method: "POST",
        body: input,
        accessToken,
      }),
    onSuccess: () => {
      // A new rule can retroactively change how future imports/rows get
      // categorised -- nothing existing changes shape, so there's no
      // "categorisation rules" query to invalidate, but invalidating
      // transactions/imports keeps any in-flight review screen accurate
      // if the user creates a rule mid-review.
      queryClient.invalidateQueries({ queryKey: ["imports"] });
    },
  });
}
