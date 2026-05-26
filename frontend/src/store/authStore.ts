import { create } from "zustand";
import type { User } from "./types";

interface AuthState {
  user: User | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  isBootstrapping: boolean;

  setAuth: (accessToken: string, user: User) => void;
  setUser: (user: User) => void;
  clearAuth: () => void;
  setBootstrapping: (v: boolean) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  accessToken: null,
  isAuthenticated: false,
  isBootstrapping: true,

  setAuth: (accessToken, user) =>
    set({ accessToken, user, isAuthenticated: true, isBootstrapping: false }),

  setUser: (user) => set({ user }),

  clearAuth: () =>
    set({ accessToken: null, user: null, isAuthenticated: false, isBootstrapping: false }),

  setBootstrapping: (v) => set({ isBootstrapping: v }),
}));
