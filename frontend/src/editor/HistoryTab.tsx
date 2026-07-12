import { History, Redo2, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useEditorStore } from "../store/editorStore";

/**
 * History tab — clickable list of every version in `assetHistory`. Header owns
 * Undo/Redo mini-buttons; rows call `jumpToHistory(index)`. Rows after the
 * current index render as "future" (dimmed + strikethrough) since they'll be
 * discarded on the next edit.
 */
export default function HistoryTab() {
  const assetHistory = useEditorStore((s) => s.assetHistory);
  const historyLabels = useEditorStore((s) => s.historyLabels);
  const currentIndex = useEditorStore((s) => s.currentIndex);
  const canUndo = useEditorStore((s) => s.canUndo());
  const canRedo = useEditorStore((s) => s.canRedo());
  const undo = useEditorStore((s) => s.undo);
  const redo = useEditorStore((s) => s.redo);
  const jumpToHistory = useEditorStore((s) => s.jumpToHistory);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-muted-foreground" />
          <h3 className="text-sm font-medium">History</h3>
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
        {assetHistory.length === 0 ? (
          <p className="p-4 text-xs text-muted-foreground">
            History appears here after you make your first edit.
          </p>
        ) : (
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
                        ? "Redo forward — discarded on next edit"
                        : "Jump back to this version"
                  }
                >
                  <div className="flex-1 min-w-0">
                    <p
                      className={`font-medium truncate ${isFuture ? "line-through" : ""}`}
                    >
                      {label}
                    </p>
                    <p className="text-muted-foreground mt-0.5">
                      v{idx + 1}
                      {asset.durationSec != null && (
                        <> · {asset.durationSec.toFixed(1)}s</>
                      )}
                    </p>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
