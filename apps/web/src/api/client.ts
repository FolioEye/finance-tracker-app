const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "DELETE" | "PUT" | "PATCH";
  body?: unknown;
  accessToken?: string | null;
}

// credentials: "include" -- required so the httpOnly refresh_token cookie
// the backend sets on /login, /register, and /oauth/* is actually sent
// back on subsequent requests (e.g. a future /refresh endpoint). Every
// call goes through this one function rather than a raw fetch() per call
// site, so this behaviour (and the Authorization header shape) can't
// silently drift between call sites.
//
// FINTRACK-51/54: `body` may now be a FormData instance (statement file
// upload, imports.ts). When it is, we deliberately skip JSON.stringify
// and skip setting Content-Type ourselves -- the browser sets
// `multipart/form-data; boundary=...` automatically, and setting it
// manually here would omit the boundary and break the upload.
export async function apiRequest<TResponse>(
  path: string,
  { method = "GET", body, accessToken }: RequestOptions = {},
): Promise<TResponse> {
  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;

  const headers: Record<string, string> = {};
  if (!isFormData) {
    headers["Content-Type"] = "application/json";
  }
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    credentials: "include",
    body: body === undefined ? undefined : isFormData ? (body as FormData) : JSON.stringify(body),
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errorBody = (await response.json()) as { detail?: string };
      detail = errorBody.detail ?? detail;
    } catch {
      // Response body wasn't JSON -- fall back to statusText, already set above.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as TResponse;
  }
  return (await response.json()) as TResponse;
}
