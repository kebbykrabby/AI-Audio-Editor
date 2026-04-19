import { useState, type FormEvent } from "react";
import { requestOtp, verifyOtp } from "../api/auth";
import { ApiRequestError } from "../api/client";
import { useAuthStore } from "../store/authStore";

type Step = "request" | "verify";

export default function PhoneOtpForm() {
  const setAuth = useAuthStore((s) => s.setAuth);
  const [step, setStep] = useState<Step>("request");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onRequest = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await requestOtp(phone);
      setStep("verify");
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Could not send code");
    } finally {
      setBusy(false);
    }
  };

  const onVerify = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await verifyOtp(phone, code);
      setAuth(res.accessToken, res.user);
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Verification failed");
    } finally {
      setBusy(false);
    }
  };

  if (step === "request") {
    return (
      <form onSubmit={onRequest} className="flex flex-col gap-3">
        <label className="text-sm text-slate-300">
          Phone number (E.164, e.g. +14155551234)
          <input
            type="tel"
            required
            placeholder="+14155551234"
            value={phone}
            onChange={(e) => setPhone(e.target.value.trim())}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-slate-100"
          />
        </label>
        {error && <div className="text-sm text-red-400">{error}</div>}
        <button
          type="submit"
          disabled={busy || !phone}
          className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white disabled:opacity-60 hover:bg-blue-500"
        >
          {busy ? "Sending code…" : "Send code"}
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={onVerify} className="flex flex-col gap-3">
      <div className="text-sm text-slate-400">Code sent to {phone}</div>
      <label className="text-sm text-slate-300">
        6-digit code
        <input
          type="text"
          required
          inputMode="numeric"
          pattern="[0-9]{6}"
          minLength={6}
          maxLength={6}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          className="mt-1 w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-slate-100 tracking-widest text-center text-lg"
        />
      </label>
      {error && <div className="text-sm text-red-400">{error}</div>}
      <button
        type="submit"
        disabled={busy || code.length !== 6}
        className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white disabled:opacity-60 hover:bg-blue-500"
      >
        {busy ? "Verifying…" : "Verify"}
      </button>
      <button
        type="button"
        onClick={() => {
          setStep("request");
          setCode("");
          setError(null);
        }}
        className="text-sm text-slate-400 hover:text-slate-200"
      >
        Use a different number
      </button>
    </form>
  );
}
