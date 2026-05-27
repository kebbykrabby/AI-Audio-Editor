import { apiFetch } from "./client";

export interface CensorshipMatchers {
  variants: boolean;
  phonetic: boolean;
}

export interface CensorshipWordsState {
  builtIn: string[];
  added: string[];
  removed: string[];
  matchers: CensorshipMatchers;
}

export interface CensorshipWordsUpdate {
  added?: string[];
  removed?: string[];
  matchers?: CensorshipMatchers;
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
