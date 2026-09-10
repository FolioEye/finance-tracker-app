import { useMutation } from "@tanstack/react-query";

import { apiRequest } from "./client";
import { useAuthStore } from "../store/authStore";

export interface OAuthLoginResponse {
  user_id: string;
  email: string;
  access_token: string;
  token_type: string;
  expires_in: number;
  is_new_user: boolean;
}

export interface RefreshResponse {
  user_id: string;
  access_token: string;
  token_type: string;
  expires_in: number;
}

async function oauthLogin(
  provider: "google" | "apple",
  idToken: string,
): Promise<OAuthLoginResponse> {
  return apiRequest<OAuthLoginResponse>(`/api/v1/auth/oauth/${provider}`, {
    method: "POST",
    body: { provider, id_token: idToken },
  });
}

export function useOAuthLoginMutation(provider: "google" | "apple") {
  return useMutation({
    mutationFn: (idToken: string) => oauthLogin(provider, idToken),
  });
}

// FINTRACK-60-AC1. No body and no Authorization header: the only credential
// is the httpOnly refresh_token cookie, which apiRequest sends because of
// its `credentials: "include"`. The response carries a new access token;
// the rotated refresh token comes back as a Set-Cookie the browser handles
// for us and JS never sees (F-02 policy -- no refresh token in any body).
async function refreshSession(): Promise<RefreshResponse> {
  return apiRequest<RefreshResponse>("/api/v1/auth/refresh", { method: "POST" });
}

// One shared in-flight promise per document.
//
// The backend rotates strictly: presenting an already-rotated token is
// treated as a replay and rejected (AC5). Without this guard, two
// simultaneous callers in the same tab -- say ProtectedRoute mounting
// while an interceptor also reacts to a 401 -- would both send the same
// cookie, and the second would be correctly rejected, logging the user
// out for doing nothing wrong. Collapsing them onto one promise means one
// rotation per page load no matter how many callers ask.
//
// Note this is per-document only. Two separate tabs restored at the same
// instant can still race; ADR-017 accepts that rather than adding a
// replay-tolerant grace window, which would defeat the point of rotation.
let inFlight: Promise<RefreshResponse> | null = null;

export function refreshSessionOnce(): Promise<RefreshResponse> {
  if (!inFlight) {
    inFlight = refreshSession().finally(() => {
      inFlight = null;
    });
  }
  return inFlight;
}

// FINTRACK-60-AC2. Called once at app start, before React renders the
// routes. Resolves either way -- a rejected refresh is a normal outcome
// for a first-time visitor with no cookie (AC4 / the no-cookie edge case),
// not an error to surface. What matters is that bootstrapState always
// reaches "done", so ProtectedRoute can never be left spinning.
export async function bootstrapSession(): Promise<void> {
  const { setSession, markBootstrapped } = useAuthStore.getState();
  try {
    const result = await refreshSessionOnce();
    setSession({
      accessToken: result.access_token,
      userId: result.user_id,
      // The refresh endpoint deliberately does not return an email --
      // it is PII the session-restore path has no need to handle. Pages
      // that display it fetch it from their own authenticated endpoints.
      email: "",
    });
  } catch {
    markBootstrapped();
  }
}
