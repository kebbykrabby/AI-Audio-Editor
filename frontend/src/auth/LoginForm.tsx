import { useState, type FormEvent } from "react";
import { login } from "../api/auth";
import { ApiRequestError } from "../api/client";
import { useAuthStore } from "../store/authStore";

export default function LoginForm() {
  const setAuth = useAuthStore((s) => s.setAuth);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await login({ email, password });
      setAuth(res.accessToken, res.user);
    } catch (e) {
      const msg = e instanceof ApiRequestError ? e.message : "Sign in failed";
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <label className="text-sm text-slate-300">
        Email
        <input
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-1 w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-slate-100"
        />
      </label>
      <label className="text-sm text-slate-300">
        Password
        <input
          type="password"
          required
          autoComplete="current-password"
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-1 w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-slate-100"
        />
      </label>
      {error && <div className="text-sm text-red-400">{error}</div>}
      <button
        type="submit"
        disabled={busy}
        className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white disabled:opacity-60 hover:bg-blue-500"
      >
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
