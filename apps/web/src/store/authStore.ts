import { create } from "zustand";

// Access token lives in memory ONLY -- never localStorage/sessionStorage
// (constraint matrix: JWT access token, 15 min, in-memory). The refresh
// token is never touched by frontend code at all; it's an httpOnly Secure
// cookie the backend sets and reads directly
// (apps/api/presentation/api/v1/auth.py), invisible to any JS running on
// this page -- the whole point of httpOnly.
interface AuthState {
  accessToken: string | null;
  userId: string | null;
  email: string | null;
  setSession: (params: { accessToken: string; userId: string; email: string }) => void;
  clearSession: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  userId: null,
  email: null,
  setSession: ({ accessToken, userId, email }) => set({ accessToken, userId, email }),
  clearSession: () => set({ accessToken: null, userId: null, email: null }),
}));
