import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { resetPassword } from "../api/auth";
import { ApiRequestError } from "../api/client";
import AuthLayout from "../auth/AuthLayout";

/**
 * Anonymous reset-password page. Accepts:
 *   - email (prefilled from `?email=` if the user came from ForgotPasswordPage)
 *   - 6-digit code from the reset email
 *   - new password (min 8 chars)
 * On success, redirects to the sign-in screen. Reset revokes all outstanding
 * refresh tokens server-side, so any existing session on any device is
 * logged out too.
 */
export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const [email, setEmail] = useState(params.get("email") ?? "");
  const [code, setCode] = useState("");
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    if (!/^\d{6}$/.test(code.trim())) {
      setError("Enter the 6-digit code from the reset email.");
      return;
    }
    if (pw.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    try {
      await resetPassword(email, code.trim(), pw);
      navigate("/?reset=success");
    } catch (e) {
      const msg = e instanceof ApiRequestError ? e.message : "Reset failed";
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      title="Set a new password"
      subtitle="Enter the code we sent to your email and choose a new password."
      footer={
        <>
          Didn't get a code?{" "}
          <Link to="/forgot-password" className="text-primary hover:underline">
            Request a new one
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <div className="space-y-1">
          <Label htmlFor="rp-email">Email</Label>
          <Input
            id="rp-email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="rp-code">6-digit code</Label>
          <Input
            id="rp-code"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="123456"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            className="font-mono tracking-widest text-center text-lg"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="rp-pw">New password</Label>
          <Input
            id="rp-pw"
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">At least 8 characters.</p>
        </div>
        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-sm text-destructive">
            {error}
          </div>
        )}
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Resetting…" : "Set new password"}
        </Button>
      </form>
    </AuthLayout>
  );
}
