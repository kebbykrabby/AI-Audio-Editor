import { useEffect, useRef, useState } from "react";
import { requestEmailVerify, verifyEmail } from "../api/auth";
import { ApiRequestError } from "../api/client";
import { useAuthStore } from "../store/authStore";

type Props = {
  email: string;
  onClose: () => void;
  onVerified: () => void;
};

export default function EmailVerificationModal({ email, onClose, onVerified }: Props) {
  const setUser = useAuthStore((s) => s.setUser);

  const [code, setCode] = useState("");
  const [sending, setSending] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentOnce, setSentOnce] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);

  // Fire off the first code automatically when the modal opens — one round-trip
  // less for the user. Any failure surfaces as the same inline error we'd
  // show on a manual click.
  useEffect(() => {
    void handleSend(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.code === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

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
          // Race: the user got verified some other way. Close cleanly.
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
          // The old code is dead; the user has to request a fresh one before
          // trying again.
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
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="verify-email-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={(e) => {
        // Click on the backdrop closes; click on the panel doesn't propagate.
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-lg bg-slate-800 border border-slate-700 shadow-xl p-6">
        <h2 id="verify-email-title" className="text-lg font-semibold text-slate-100 mb-1">
          Verify your email
        </h2>
        <p className="text-sm text-slate-400 mb-4">
          We sent a 6-digit code to <span className="text-slate-200">{email}</span>. Enter
          it below to enable exports.
        </p>

        <form onSubmit={handleVerify} className="space-y-3">
          <input
            ref={inputRef}
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="123456"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2 text-center text-lg tracking-[0.4em] font-mono text-slate-100 focus:border-blue-500 focus:outline-none"
          />

          {error && (
            <p role="alert" className="text-sm text-red-400">
              {error}
            </p>
          )}
          {!error && notice && (
            <p className="text-sm text-emerald-400">{notice}</p>
          )}
          {!error && !notice && sentOnce && (
            <p className="text-sm text-slate-500">
              Code expires in 15 minutes. Check your spam folder if it doesn't arrive.
            </p>
          )}

          <div className="flex gap-2 pt-1">
            <button
              type="submit"
              disabled={verifying || code.length !== 6}
              className="flex-1 rounded bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed px-3 py-2 text-sm font-medium text-white transition-colors"
            >
              {verifying ? "Verifying…" : "Verify"}
            </button>
            <button
              type="button"
              onClick={() => void handleSend(false)}
              disabled={sending}
              className="rounded border border-slate-600 px-3 py-2 text-sm text-slate-300 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {sending ? "Sending…" : "Resend code"}
            </button>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="w-full text-xs text-slate-500 hover:text-slate-300 mt-2"
          >
            Cancel
          </button>
        </form>
      </div>
    </div>
  );
}
