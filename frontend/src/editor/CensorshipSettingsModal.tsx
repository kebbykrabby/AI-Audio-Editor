import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import {
  getCensorshipWords,
  updateCensorshipWords,
  type CensorshipMatchers,
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
 * scrollable grid of the built-in words with per-row checkboxes (unchecked
 * = added to the user's `removed` list).
 *
 * Reloads on every open so a stale tab can't clobber later edits from
 * another device.
 */
export default function CensorshipSettingsModal({ open, onClose }: Props) {
  const [state, setState] = useState<CensorshipWordsState | null>(null);
  const [addedText, setAddedText] = useState("");
  const [removedSet, setRemovedSet] = useState<Set<string>>(new Set());
  const [matchers, setMatchers] = useState<CensorshipMatchers>({
    variants: true,
    phonetic: false,
  });
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
        setMatchers(s.matchers);
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
        matchers,
      });
      setState(next);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save changes");
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
    <Dialog open={open} onOpenChange={(v) => !v && !saving && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Censorship word list</DialogTitle>
          <DialogDescription>
            Manage your custom words and toggle which built-in words the detector uses.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="py-6 text-sm text-muted-foreground">Loading…</div>
        ) : (
          <div className="space-y-5 max-h-[60vh] overflow-y-auto pr-1">
            <section className="space-y-2">
              <Label className="text-xs uppercase tracking-wide">
                Custom words to censor
              </Label>
              <p className="text-xs text-muted-foreground">
                One word per line. Lowercase + punctuation are normalized. These words
                are always censored, on top of any built-in words you keep enabled.
              </p>
              <Textarea
                value={addedText}
                onChange={(e) => setAddedText(e.target.value)}
                disabled={saving}
                className="h-32 font-mono text-sm"
                placeholder={"banana\ncustom-slur\n..."}
              />
            </section>

            <section className="space-y-2">
              <Label className="text-xs uppercase tracking-wide">Built-in words</Label>
              <p className="text-xs text-muted-foreground">
                Uncheck a word to stop censoring it. Re-check to restore it.
              </p>
              <ScrollArea className="max-h-56 rounded-md border border-border p-2">
                <ul className="grid grid-cols-2 sm:grid-cols-3 gap-x-3 gap-y-1 text-xs">
                  {sortedBuiltIn.map((w) => {
                    const enabled = !removedSet.has(w);
                    return (
                      <li key={w} className="flex items-center gap-1.5">
                        <Checkbox
                          id={`builtin-${w}`}
                          checked={enabled}
                          onCheckedChange={() => toggleBuiltIn(w)}
                          disabled={saving}
                        />
                        <label
                          htmlFor={`builtin-${w}`}
                          className={`font-mono cursor-pointer ${
                            enabled ? "text-foreground" : "text-muted-foreground line-through"
                          }`}
                        >
                          {w}
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </ScrollArea>
            </section>

            <section className="space-y-2">
              <Label className="text-xs uppercase tracking-wide">Matchers</Label>
              <p className="text-xs text-muted-foreground">
                Exact matching is always on. Variants catches inflected forms
                (running, ran, runs). Phonetic catches sound-alike mistranscriptions
                — applied only to your custom words to avoid built-in false
                positives.
              </p>
              <div className="flex flex-col gap-2 text-sm">
                <label className="flex items-center gap-2 text-muted-foreground">
                  <Checkbox checked disabled />
                  <span>Exact (always on)</span>
                </label>
                <label className="flex items-center gap-2">
                  <Checkbox
                    checked={matchers.variants}
                    onCheckedChange={(v) =>
                      setMatchers((m) => ({ ...m, variants: v === true }))
                    }
                    disabled={saving}
                  />
                  <span>
                    Variants{" "}
                    <span className="text-muted-foreground">(stems + plurals)</span>
                  </span>
                </label>
                <label className="flex items-center gap-2">
                  <Checkbox
                    checked={matchers.phonetic}
                    onCheckedChange={(v) =>
                      setMatchers((m) => ({ ...m, phonetic: v === true }))
                    }
                    disabled={saving}
                  />
                  <span>
                    Phonetic{" "}
                    <span className="text-muted-foreground">
                      (your custom words only)
                    </span>
                  </span>
                </label>
              </div>
            </section>

            {error && (
              <p className="text-xs text-destructive bg-destructive/10 border border-destructive/30 rounded-md p-2">
                {error}
              </p>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving || loading}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
