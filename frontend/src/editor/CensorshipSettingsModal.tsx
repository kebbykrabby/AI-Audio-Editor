import { useEffect, useMemo, useState } from "react";
import {
  getCensorshipWords,
  updateCensorshipWords,
  type CensorshipWordsState,
} from "../api/censorship";

interface Props {
  open: boolean;
  onClose: () => void;
}

/**
 * Censorship word-list editor (Phase 3 / D6).
 *
 * Two surfaces: a textarea for the user's custom words (added), and a
 * scrollable list of the built-in words with per-row checkboxes that toggle
 * inclusion (unchecked = added to the user's `removed` list).
 *
 * The modal loads fresh on every open so a stale tab can't overwrite later
 * edits from another device.
 */
export default function CensorshipSettingsModal({ open, onClose }: Props) {
  const [state, setState] = useState<CensorshipWordsState | null>(null);
  const [addedText, setAddedText] = useState("");
  const [removedSet, setRemovedSet] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    getCensorshipWords()
      .then((s) => {
        setState(s);
        setAddedText(s.added.join("\n"));
        setRemovedSet(new Set(s.removed));
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load word list"),
      )
      .finally(() => setLoading(false));
  }, [open]);

  const sortedBuiltIn = useMemo(
    () => (state ? [...state.builtIn].sort() : []),
    [state],
  );

  if (!open) return null;

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const addedList = addedText
        .split(/\r?\n/)
        .map((s) => s.trim())
        .filter(Boolean);
      const removedList = Array.from(removedSet);
      const next = await updateCensorshipWords({
        added: addedList,
        removed: removedList,
      });
      setState(next);
      onClose();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to save changes",
      );
    } finally {
      setSaving(false);
    }
  };

  const toggleBuiltIn = (word: string) => {
    setRemovedSet((prev) => {
      const next = new Set(prev);
      if (next.has(word)) next.delete(word);
      else next.add(word);
      return next;
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      onClick={(e) => {
        // Click outside the panel closes the modal.
        if (e.target === e.currentTarget && !saving) onClose();
      }}
    >
      <div className="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-2xl max-h-[80vh] flex flex-col">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-200">
            Censorship word list
          </h3>
          <button
            onClick={onClose}
            disabled={saving}
            className="text-slate-400 hover:text-slate-100 text-lg leading-none"
            aria-label="Close"
            title="Close"
          >
            ×
          </button>
        </div>

        {loading ? (
          <div className="p-6 text-sm text-slate-400">Loading…</div>
        ) : (
          <div className="overflow-y-auto p-4 space-y-4">
            <section>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-1">
                Custom words to censor
              </h4>
              <p className="text-xs text-slate-500 mb-2">
                One word per line. Lowercase + punctuation are normalized. These
                words are always censored, on top of any built-in words you keep
                enabled.
              </p>
              <textarea
                value={addedText}
                onChange={(e) => setAddedText(e.target.value)}
                disabled={saving}
                className="w-full h-32 bg-slate-800 border border-slate-700 rounded p-2 text-sm text-slate-200 font-mono"
                placeholder="banana&#10;custom-slur&#10;..."
              />
            </section>

            <section>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-1">
                Built-in words
              </h4>
              <p className="text-xs text-slate-500 mb-2">
                Uncheck a word to stop censoring it. Re-check to restore it.
              </p>
              <ul className="grid grid-cols-2 sm:grid-cols-3 gap-x-3 gap-y-1 text-xs">
                {sortedBuiltIn.map((w) => {
                  const enabled = !removedSet.has(w);
                  return (
                    <li key={w} className="flex items-center gap-1.5">
                      <input
                        id={`builtin-${w}`}
                        type="checkbox"
                        checked={enabled}
                        onChange={() => toggleBuiltIn(w)}
                        disabled={saving}
                      />
                      <label
                        htmlFor={`builtin-${w}`}
                        className={`font-mono ${
                          enabled ? "text-slate-300" : "text-slate-500 line-through"
                        }`}
                      >
                        {w}
                      </label>
                    </li>
                  );
                })}
              </ul>
            </section>

            {error && (
              <p className="text-xs text-red-400 bg-red-950 border border-red-900 rounded p-2">
                {error}
              </p>
            )}
          </div>
        )}

        <div className="p-4 border-t border-slate-800 flex justify-end gap-2">
          <button onClick={onClose} disabled={saving} className="op-btn">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || loading}
            className="op-btn"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
