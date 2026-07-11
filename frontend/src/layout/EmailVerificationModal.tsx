import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { requestEmailVerify, verifyEmail } from "../api/auth";
import { ApiRequestError } from "../api/client";
import { useAuthStore } from "../store/authStore";

type Props = {
  email: string;
  onClose: () => void;
  onVerified: () => void;
};

/**
 * Modal that runs the email-verification flow before the first export.
 * Auto-requests a code on mount (one round-trip less for the user); handles
 * resend + retry-on-verify. See `ExportPopover` for the caller.
 */
export default function EmailVerificationModal({ email, onClose, onVerified }: Props) {
  const setUser = useAuthStore((s) => s.setUser);

  const [code, setCode] = useState("");
  const [sending, setSending] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentOnce, setSentOnce] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void handleSend(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function handleSend(silent = false) {
    setError(null);
    setNotice(null);
    setSending(true);
    try {
      await requestEmailVerify();
      setSentOnce(true);
      if (!silent) setNotice("A new code has been sent to your inbox.");
    } catch (e: unknown) {
      if (e instanceof ApiRequestError) {
        if (e.code === "EMAIL_ALREADY_VERIFIED") {
          onVerified();
          return;
        }
        setError(e.message);
      } else {
        setError("Couldn't send code. Please try again.");
      }
    } finally {
      setSending(false);
    }
  }

  async function handleVerify(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = code.trim();
    if (!/^\d{6}$/.test(trimmed)) {
      setError("Enter the 6-digit code from your email.");
      return;
    }
    setError(null);
    setNotice(null);
    setVerifying(true);
    try {
      const user = await verifyEmail(trimmed);
      setUser(user);
      onVerified();
    } catch (e: unknown) {
      if (e instanceof ApiRequestError) {
        setError(e.message);
        if (e.code === "CODE_EXHAUSTED") {
          setCode("");
        }
      } else {
        setError("Verification failed. Please try again.");
      }
    } finally {
      setVerifying(false);
    }
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Verify your email</DialogTitle>
          <DialogDescription>
            We sent a 6-digit code to{" "}
            <span className="text-foreground font-medium">{email}</span>. Enter it
            below to enable exports.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleVerify} className="space-y-3">
          <Input
            ref={inputRef}
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="123456"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            className="text-center text-lg tracking-[0.4em] font-mono h-11"
          />

          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          {!error && notice && (
            <p className="text-sm text-emerald-600">{notice}</p>
          )}
          {!error && !notice && sentOnce && (
            <p className="text-sm text-muted-foreground">
              Code expires in 15 minutes. Check your spam folder if it doesn't arrive.
            </p>
          )}

          <div className="flex gap-2 pt-1">
            <Button
              type="submit"
              disabled={verifying || code.length !== 6}
              className="flex-1"
            >
              {verifying ? "Verifying…" : "Verify"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => void handleSend(false)}
              disabled={sending}
            >
              {sending ? "Sending…" : "Resend code"}
            </Button>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="w-full text-xs text-muted-foreground hover:text-foreground mt-1"
          >
            Cancel
          </button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
