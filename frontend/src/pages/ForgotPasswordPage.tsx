import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { requestPasswordReset } from "../api/auth";
import AuthLayout from "../auth/AuthLayout";

/**
 * Anonymous forgot-password page. Sends the email to
 * `/api/auth/password/forgot` (which always returns 204 for anti-enumeration)
 * and shows a success confirmation regardless of whether the email exists.
 */
export default function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      await requestPasswordReset(email);
    } catch {
      // Endpoint is 204 on the success path; if a real error surfaces (network
      // failure, etc.) we still show the generic "check your inbox" screen —
      // showing a differentiated error here would leak whether the email
      // exists.
    } finally {
      setBusy(false);
      setSent(true);
    }
  };

  if (sent) {
    return (
      <AuthLayout
        title="Check your inbox"
        subtitle="If an account exists for that email, we've sent a 6-digit code to reset your password."
        footer={
          <>
            Didn't get one?{" "}
            <button
              type="button"
              onClick={() => setSent(false)}
              className="text-primary hover:underline"
            >
              Try again
            </button>
          </>
        }
      >
        <Button
          type="button"
          className="w-full"
          onClick={() =>
            navigate(`/reset-password?email=${encodeURIComponent(email)}`)
          }
        >
          I have a code
        </Button>
        <div className="mt-3 text-center">
          <Link to="/" className="text-sm text-muted-foreground hover:text-foreground">
            Back to sign in
          </Link>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Reset your password"
      subtitle="Enter your email and we'll send you a 6-digit code to set a new one."
      footer={
        <>
          Remembered it?{" "}
          <Link to="/" className="text-primary hover:underline">
            Back to sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <div className="space-y-1">
          <Label htmlFor="fp-email">Email</Label>
          <Input
            id="fp-email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Sending…" : "Send reset code"}
        </Button>
      </form>
    </AuthLayout>
  );
}
