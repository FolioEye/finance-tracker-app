import { useMutation } from "@tanstack/react-query";

import { apiRequest } from "./client";

export interface OAuthLoginResponse {
  user_id: string;
  email: string;
  access_token: string;
  token_type: string;
  expires_in: number;
  is_new_user: boolean;
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
