import { create } from "zustand";

// Access token lives in memory ONLY -- never localStorage/sessionStorage
// (constraint matrix: JWT access token, 15 min, in-memory). The refresh
// token is never touched by frontend code at all; it's an httpOnly Secure
// cookie the backend sets and reads directly
// (apps/api/presentation/api/v1/auth.py), invisible to any JS running on
// this page -- the whole point of httpOnly.
//
// FINTRACK-60: `bootstrapState` tracks the one-shot silent-refresh attempt
// made on app load. It starts "pending" so ProtectedRoute holds its
// redirect decision until we know whether a valid refresh cookie exists;
// without it, a page reload always looks identical to being logged out.
// It reaches "done" exactly once per page load, on either outcome --
// a failed refresh is a completed bootstrap, not a stuck one.
export type BootstrapState = "pending" | "done";

interface AuthState {
  accessToken: string | null;
  userId: string | null;
  email: string | null;
  bootstrapState: BootstrapState;
  setSession: (params: { accessToken: string; userId: string; email: string }) => void;
  clearSession: () => void;
  markBootstrapped: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  userId: null,
  email: null,
  bootstrapState: "pending",
  // A successful refresh or login is itself proof the bootstrap finished,
  // so setSession marks it done too -- that way no call site can leave the
  // app spinning by remembering the token but forgetting the flag.
  setSession: ({ accessToken, userId, email }) =>
    set({ accessToken, userId, email, bootstrapState: "done" }),
  // clearSession deliberately does NOT reset bootstrapState to "pending":
  // logging out is a finished bootstrap, and resetting it would send
  // ProtectedRoute back to the spinner instead of to /login.
  clearSession: () => set({ accessToken: null, userId: null, email: null }),
  markBootstrapped: () => set({ bootstrapState: "done" }),
}));
