import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { Spinner } from "./ui/Spinner";
import { useAuthStore } from "../store/authStore";

interface ProtectedRouteProps {
  children: ReactNode;
}

// FINTRACK-60-AC2/AC3: the redirect decision must not be made until the
// silent-refresh attempt started in main.tsx has resolved. Before this
// story, a page reload cleared the in-memory access token and this
// component redirected immediately -- which is exactly the bug, since a
// valid refresh cookie may be sitting there unread.
//
// Gating on `bootstrapState` rather than on `accessToken` alone is what
// makes AC3 hold too: React Router keeps the requested location while we
// render the spinner, so a successful refresh lands the user on the route
// they actually asked for, query params intact, and they never see the
// /login screen at all -- not even for one frame.
export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const accessToken = useAuthStore((state) => state.accessToken);
  const bootstrapState = useAuthStore((state) => state.bootstrapState);

  if (bootstrapState === "pending") {
    return (
      <div
        className="flex min-h-screen items-center justify-center"
        role="status"
        aria-live="polite"
        aria-label="Restoring your session"
      >
        <Spinner />
      </div>
    );
  }

  if (!accessToken) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
