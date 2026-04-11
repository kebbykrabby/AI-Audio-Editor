import type { ApiError } from "../store/types";

export class ApiRequestError extends Error {
  code: string;
  details?: { field?: string; constraint?: string; received?: number | string };

  constructor(code: string, message: string, details?: ApiError["error"]["details"]) {
    super(message);
    this.code = code;
    this.details = details;
  }
}

export async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);

  if (!res.ok) {
    let body: ApiError | null = null;
    try {
      body = await res.json();
    } catch {
      // non-JSON error
    }
    if (body?.error) {
      throw new ApiRequestError(body.error.code, body.error.message, body.error.details);
    }
    throw new ApiRequestError("UNKNOWN", `Request failed: ${res.status} ${res.statusText}`);
  }

  return res.json();
}
