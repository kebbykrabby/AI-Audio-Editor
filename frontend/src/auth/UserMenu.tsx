import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { logout } from "../api/auth";
import { useAuthStore } from "../store/authStore";
import { useEditorStore } from "../store/editorStore";

export default function UserMenu() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const resetEditor = useEditorStore((s) => s.reset);
  const [busy, setBusy] = useState(false);

  if (!user) return null;

  const label = user.displayName || user.email || "Account";

  const onLogout = async () => {
    setBusy(true);
    try {
      await logout();
    } catch {
      // best-effort; clear local state regardless
    }
    resetEditor();
    clearAuth();
    setBusy(false);
    navigate("/");
  };

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground truncate max-w-[200px]">{label}</span>
      <button
        type="button"
        onClick={onLogout}
        disabled={busy}
        className="px-2 py-1 rounded border border-border text-foreground hover:bg-muted disabled:opacity-50"
      >
        {busy ? "…" : "Sign out"}
      </button>
    </div>
  );
}
