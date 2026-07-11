import { useState } from "react";
import { Apple } from "lucide-react";

import { Button } from "@/components/ui/button";
import { oauthStart } from "../api/auth";
import { ApiRequestError } from "../api/client";
import GoogleIcon from "./GoogleIcon";

/**
 * Two-button OAuth strip mounted in the AuthGate. Each button starts the
 * corresponding provider's flow via `/api/auth/oauth/{provider}/start`, then
 * navigates the browser to the returned redirect URL. On failure (503 when
 * the provider isn't configured) we surface the message via the `onError`
 * callback so the parent can render it inline.
 */
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
      <Button
        type="button"
        variant="outline"
        disabled={busy !== null}
        onClick={() => go("google")}
        className="w-full gap-2"
      >
        <GoogleIcon className="w-4 h-4" />
        {busy === "google" ? "Redirecting…" : "Continue with Google"}
      </Button>
      <Button
        type="button"
        variant="outline"
        disabled={busy !== null}
        onClick={() => go("apple")}
        className="w-full gap-2"
      >
        <Apple className="w-4 h-4" />
        {busy === "apple" ? "Redirecting…" : "Continue with Apple"}
      </Button>
    </div>
  );
}
