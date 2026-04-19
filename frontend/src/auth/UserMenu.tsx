import { useState } from "react";
import { logout } from "../api/auth";
import { useAuthStore } from "../store/authStore";
import { useEditorStore } from "../store/editorStore";

export default function UserMenu() {
  const user = useAuthStore((s) => s.user);
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const resetEditor = useEditorStore((s) => s.reset);
  const [busy, setBusy] = useState(false);

  if (!user) return null;

  const label = user.displayName || user.email || user.phoneNumber || "Account";

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
  };

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-slate-400 truncate max-w-[200px]">{label}</span>
      <button
        type="button"
        onClick={onLogout}
        disabled={busy}
        className="px-2 py-1 rounded border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
      >
        {busy ? "…" : "Sign out"}
      </button>
    </div>
  );
}
