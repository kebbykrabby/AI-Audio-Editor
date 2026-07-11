import { Check, History, Redo2, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useEditorStore } from "../store/editorStore";

/**
 * Version History panel — every entry the store's `assetHistory` has,
 * rendered as a clickable row. Click a row → `jumpToHistory(index)`; rows
 * past the current index are grayed (they'd be discarded if the user then
 * made a new edit — same semantics as browser back/forward history).
 *
 * No backend query — this is entirely session-local state. On page reload,
 * `useRestoreSession` walks the `parentAssetId` chain from the persisted
 * tip and gives each restored entry a generic "Version N" label.
 */
export default function VersionHistoryPanel() {
  const assetHistory = useEditorStore((s) => s.assetHistory);
  const historyLabels = useEditorStore((s) => s.historyLabels);
  const currentIndex = useEditorStore((s) => s.currentIndex);
  const canUndo = useEditorStore((s) => s.canUndo());
  const canRedo = useEditorStore((s) => s.canRedo());
  const undo = useEditorStore((s) => s.undo);
  const redo = useEditorStore((s) => s.redo);
  const jumpToHistory = useEditorStore((s) => s.jumpToHistory);

  if (assetHistory.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-card shadow-sm flex flex-col max-h-[70vh]">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-muted-foreground" />
          <h3 className="text-sm font-medium">History</h3>
          <span className="text-xs text-muted-foreground">
            ({assetHistory.length})
          </span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            disabled={!canUndo}
            onClick={undo}
            title="Undo (Ctrl+Z)"
          >
            <Undo2 className="w-3.5 h-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            disabled={!canRedo}
            onClick={redo}
            title="Redo (Ctrl+Y)"
          >
            <Redo2 className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-2 space-y-0.5">
          {assetHistory.map((asset, idx) => {
            const label = historyLabels[idx] ?? `Version ${idx + 1}`;
            const isCurrent = idx === currentIndex;
            const isFuture = idx > currentIndex;
            return (
              <button
                key={asset.assetId}
                onClick={() => jumpToHistory(idx)}
                className={`w-full text-left px-3 py-2 rounded-md text-xs transition-all ${
                  isCurrent
                    ? "bg-primary/10 text-primary border border-primary/30"
                    : isFuture
                      ? "text-muted-foreground/60 hover:bg-accent/50"
                      : "text-foreground hover:bg-accent"
                }`}
                title={
                  isCurrent
                    ? "Current version"
                    : isFuture
                      ? "Redo forward — discarded on the next edit"
                      : "Jump back to this version"
                }
              >
                <div className="flex items-center gap-2">
                  {isCurrent && <Check className="w-3 h-3 shrink-0" />}
                  <div className="flex-1 min-w-0">
                    <p
                      className={`font-medium truncate ${
                        isFuture ? "line-through" : ""
                      }`}
                    >
                      {label}
                    </p>
                    <p className="text-muted-foreground mt-0.5 font-mono">
                      v{idx + 1}
                      {asset.durationSec != null && (
                        <> · {asset.durationSec.toFixed(1)}s</>
                      )}
                    </p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </ScrollArea>
    </div>
  );
}
