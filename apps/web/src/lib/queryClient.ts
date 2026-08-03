import { QueryClient } from "@tanstack/react-query";

// Sensible defaults for a finance app: don't silently retry a failed
// mutation (never double-submit anything money-related), do allow a
// modest retry for read queries (transient network blips), and don't
// refetch on window focus for the login/auth flows this story ships --
// avoids surprising an OAuth in-flight redirect with a background refetch.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 0,
    },
  },
});
