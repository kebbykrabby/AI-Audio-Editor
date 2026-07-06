import { useEffect, useState, type ReactNode } from "react";
import { me } from "../api/auth";
import { useAuthStore } from "../store/authStore";
import LoginForm from "./LoginForm";
import OAuthButtons from "./OAuthButtons";
import RegisterForm from "./RegisterForm";

type Tab = "login" | "register";

export default function AuthGate({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isBootstrapping = useAuthStore((s) => s.isBootstrapping);
  const setUser = useAuthStore((s) => s.setUser);
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const setBootstrapping = useAuthStore((s) => s.setBootstrapping);

  const [tab, setTab] = useState<Tab>("login");
  const [oauthError, setOauthError] = useState<string | null>(null);

  // Surface backend-reported OAuth failures (?auth=error&provider=...&reason=...)
  // and scrub the query string so a reload doesn't re-trigger them.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("auth") === "error") {
      const provider = params.get("provider") || "provider";
      const reason = params.get("reason") || "unknown error";
      setOauthError(`Sign-in with ${provider} failed: ${reason}. Try another method.`);
      params.delete("auth");
      params.delete("provider");
      params.delete("reason");
      const qs = params.toString();
      window.history.replaceState(
        {},
        "",
        window.location.pathname + (qs ? `?${qs}` : ""),
      );
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const user = await me();
        if (!cancelled) {
          // apiFetch already set accessToken via silent refresh; just ensure user is current.
          setUser(user);
          setBootstrapping(false);
        }
      } catch {
        if (!cancelled) clearAuth();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [setUser, clearAuth, setBootstrapping]);

  if (isBootstrapping) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-slate-400 text-sm">Signing you in…</div>
      </div>
    );
  }

  if (isAuthenticated) {
    return <>{children}</>;
  }

  return (
    <div className="flex items-center justify-center min-h-screen px-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-800 bg-slate-900 p-6 shadow-xl">
        <h1 className="text-lg font-semibold text-slate-100 mb-4">AI Audio Editor</h1>

        <div className="flex gap-1 mb-4 text-sm">
          {(["login", "register"] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded-md ${
                tab === t
                  ? "bg-slate-700 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {t === "login" ? "Sign in" : "Register"}
            </button>
          ))}
        </div>

        {tab === "login" && <LoginForm />}
        {tab === "register" && <RegisterForm />}

        <div className="my-4 border-t border-slate-800" />

        <OAuthButtons onError={setOauthError} />
        {oauthError && <div className="mt-2 text-sm text-red-400">{oauthError}</div>}
      </div>
    </div>
  );
}
