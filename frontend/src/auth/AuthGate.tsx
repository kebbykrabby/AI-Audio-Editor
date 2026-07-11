import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { me } from "../api/auth";
import { useAuthStore } from "../store/authStore";
import AuthLayout from "./AuthLayout";
import LoginForm from "./LoginForm";
import OAuthButtons from "./OAuthButtons";
import RegisterForm from "./RegisterForm";

/** Read `?reset=success` set by the reset-password page and clear it from the URL. */
function useResetSuccessBanner(): boolean {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("reset") === "success") {
      setShown(true);
      params.delete("reset");
      const qs = params.toString();
      window.history.replaceState(
        {},
        "",
        window.location.pathname + (qs ? `?${qs}` : ""),
      );
    }
  }, []);
  return shown;
}

type Tab = "login" | "register";

/**
 * The gate + the auth screen. When the user hasn't authenticated yet, this
 * renders the Login / Register tabs + OAuth buttons inside an `AuthLayout`
 * card. When they have, it renders the app content.
 *
 * Also owns:
 *   - Bootstrapping (`/api/auth/me` on mount → hydrate `authStore`)
 *   - Surfacing OAuth failures via the `?auth=error&provider=…&reason=…`
 *     query string set by the backend callback redirect.
 */
export default function AuthGate({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isBootstrapping = useAuthStore((s) => s.isBootstrapping);
  const setUser = useAuthStore((s) => s.setUser);
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const setBootstrapping = useAuthStore((s) => s.setBootstrapping);

  const [tab, setTab] = useState<Tab>("login");
  const [oauthError, setOauthError] = useState<string | null>(null);
  const resetSuccess = useResetSuccessBanner();

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
      <div className="flex items-center justify-center min-h-screen bg-background">
        <div className="text-muted-foreground text-sm">Signing you in…</div>
      </div>
    );
  }

  if (isAuthenticated) {
    return <>{children}</>;
  }

  return (
    <AuthLayout
      title={tab === "login" ? "Welcome back" : "Create your account"}
      subtitle={
        tab === "login"
          ? "Sign in to keep editing your projects."
          : "One account for every project you edit."
      }
      footer={
        tab === "login" ? (
          <>
            Forgot your password?{" "}
            <Link to="/forgot-password" className="text-primary hover:underline">
              Reset it
            </Link>
          </>
        ) : (
          <>
            Already have an account?{" "}
            <button
              type="button"
              onClick={() => setTab("login")}
              className="text-primary hover:underline"
            >
              Sign in
            </button>
          </>
        )
      }
    >
      {/* Tab switcher */}
      <div className="grid grid-cols-2 gap-1 rounded-md bg-muted p-1 mb-5">
        {(["login", "register"] as Tab[]).map((t) => (
          <Button
            key={t}
            type="button"
            variant={tab === t ? "default" : "ghost"}
            size="sm"
            onClick={() => setTab(t)}
            className="h-8"
          >
            {t === "login" ? "Sign in" : "Register"}
          </Button>
        ))}
      </div>

      <OAuthButtons onError={setOauthError} />

      <div className="my-4 flex items-center gap-2 text-xs text-muted-foreground">
        <div className="flex-1 border-t border-border" />
        <span>or continue with email</span>
        <div className="flex-1 border-t border-border" />
      </div>

      {resetSuccess && tab === "login" && (
        <div className="mb-3 rounded-md border border-emerald-300 bg-emerald-50 p-2 text-sm text-emerald-900">
          Password reset. Sign in with your new password.
        </div>
      )}

      {tab === "login" ? <LoginForm /> : <RegisterForm />}

      {oauthError && (
        <div className="mt-4 rounded-md border border-destructive/30 bg-destructive/10 p-2 text-sm text-destructive">
          {oauthError}
        </div>
      )}
    </AuthLayout>
  );
}
