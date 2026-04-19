import { useAuthStore } from "../store/authStore";
import type { ApiError, TokenResponse } from "../store/types";

export class ApiRequestError extends Error {
  code: string;
  status: number;
  details?: { field?: string; constraint?: string; received?: number | string };

  constructor(
    code: string,
    message: string,
    status = 0,
    details?: ApiError["error"]["details"],
  ) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

function readCookie(name: string): string | null {
  const prefix = name + "=";
  const parts = document.cookie.split(";");
  for (const raw of parts) {
    const c = raw.trim();
    if (c.startsWith(prefix)) return decodeURIComponent(c.substring(prefix.length));
  }
  return null;
}

const SKIP_REFRESH_URLS = [
  "/api/auth/refresh",
  "/api/auth/login",
  "/api/auth/register",
  "/api/auth/phone/verify-otp",
];

let refreshInFlight: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    const csrf = readCookie("csrf");
    const headers: Record<string, string> = {};
    if (csrf) headers["X-CSRF-Token"] = csrf;

    try {
      const res = await fetch("/api/auth/refresh", {
        method: "POST",
        credentials: "include",
        headers,
      });
      if (!res.ok) {
        useAuthStore.getState().clearAuth();
        return null;
      }
      const data: TokenResponse = await res.json();
      useAuthStore.getState().setAuth(data.accessToken, data.user);
      return data.accessToken;
    } catch {
      useAuthStore.getState().clearAuth();
      return null;
    }
  })();

  try {
    return await refreshInFlight;
  } finally {
    refreshInFlight = null;
  }
}

function buildHeaders(
  initHeaders: HeadersInit | undefined,
  accessToken: string | null,
): Headers {
  const headers = new Headers(initHeaders);
  if (accessToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  const csrf = readCookie("csrf");
  if (csrf && !headers.has("X-CSRF-Token")) {
    headers.set("X-CSRF-Token", csrf);
  }
  return headers;
}

async function rawFetch(url: string, options: RequestInit, accessToken: string | null): Promise<Response> {
  return fetch(url, {
    ...options,
    credentials: "include",
    headers: buildHeaders(options.headers, accessToken),
  });
}

export async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  const { accessToken } = useAuthStore.getState();

  let res = await rawFetch(url, options, accessToken);

  if (res.status === 401 && !SKIP_REFRESH_URLS.some((skip) => url.startsWith(skip))) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      res = await rawFetch(url, options, newToken);
    }
  }

  if (res.status === 204 || res.headers.get("content-length") === "0") {
    // No JSON body; swallow an empty response safely.
    if (!res.ok) {
      throw new ApiRequestError(
        "UNKNOWN",
        `Request failed: ${res.status} ${res.statusText}`,
        res.status,
      );
    }
    return undefined as T;
  }

  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      // non-JSON error; fall through
    }
  }

  if (!res.ok) {
    const apiBody = body as ApiError | { detail?: { code?: string; message?: string } } | null;
    if (apiBody && "error" in apiBody && apiBody.error) {
      throw new ApiRequestError(
        apiBody.error.code,
        apiBody.error.message,
        res.status,
        apiBody.error.details,
      );
    }
    if (apiBody && "detail" in apiBody && typeof apiBody.detail === "object" && apiBody.detail) {
      const d = apiBody.detail as { code?: string; message?: string };
      throw new ApiRequestError(
        d.code || "UNKNOWN",
        d.message || `Request failed: ${res.status}`,
        res.status,
      );
    }
    throw new ApiRequestError(
      "UNKNOWN",
      `Request failed: ${res.status} ${res.statusText}`,
      res.status,
    );
  }

  return body as T;
}
