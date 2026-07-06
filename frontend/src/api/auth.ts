import { apiFetch } from "./client";
import type { TokenResponse, User } from "../store/types";

export interface RegisterBody {
  email: string;
  password: string;
  displayName?: string;
}

export interface LoginBody {
  email: string;
  password: string;
}

export async function register(body: RegisterBody): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: body.email,
      password: body.password,
      display_name: body.displayName,
    }),
  });
}

export async function login(body: LoginBody): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function logout(): Promise<void> {
  await apiFetch<void>("/api/auth/logout", { method: "POST" });
}

export async function me(): Promise<User> {
  return apiFetch<User>("/api/auth/me", { method: "GET" });
}

export async function oauthStart(provider: "google" | "apple"): Promise<{ redirectUrl: string }> {
  return apiFetch<{ redirectUrl: string }>(`/api/auth/oauth/${provider}/start`, { method: "GET" });
}
