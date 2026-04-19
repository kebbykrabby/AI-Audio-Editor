import { useState } from "react";
import { oauthStart } from "../api/auth";
import { ApiRequestError } from "../api/client";

export default function OAuthButtons({ onError }: { onError?: (msg: string) => void }) {
  const [busy, setBusy] = useState<"google" | "apple" | null>(null);

  const go = async (provider: "google" | "apple") => {
    setBusy(provider);
    try {
      const { redirectUrl } = await oauthStart(provider);
      window.location.href = redirectUrl;
    } catch (e) {
      const msg = e instanceof ApiRequestError ? e.message : "OAuth redirect failed";
      onError?.(msg);
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        disabled={busy !== null}
        onClick={() => go("google")}
        className="w-full rounded-md bg-white text-slate-900 px-4 py-2 font-medium disabled:opacity-60 hover:bg-slate-100"
      >
        {busy === "google" ? "Redirecting…" : "Continue with Google"}
      </button>
      <button
        type="button"
        disabled={busy !== null}
        onClick={() => go("apple")}
        className="w-full rounded-md bg-black text-white px-4 py-2 font-medium disabled:opacity-60 hover:bg-slate-900"
      >
        {busy === "apple" ? "Redirecting…" : "Continue with Apple"}
      </button>
    </div>
  );
}
