import { apiFetch } from "./client";

export interface CensorshipWordsState {
  builtIn: string[];
  added: string[];
  removed: string[];
}

export interface CensorshipWordsUpdate {
  added?: string[];
  removed?: string[];
}

export async function getCensorshipWords(): Promise<CensorshipWordsState> {
  return apiFetch<CensorshipWordsState>("/api/users/me/censorship-words");
}

export async function updateCensorshipWords(
  body: CensorshipWordsUpdate,
): Promise<CensorshipWordsState> {
  return apiFetch<CensorshipWordsState>("/api/users/me/censorship-words", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
