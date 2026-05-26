import { useEffect } from "react";
import { useEditorStore } from "../store/editorStore";
import ExportPopover from "./ExportPopover";

export default function Toolbar() {
  const asset = useEditorStore((s) => s.currentAsset());
  const canUndo = useEditorStore((s) => s.canUndo());
  const canRedo = useEditorStore((s) => s.canRedo());
  const undo = useEditorStore((s) => s.undo);
  const redo = useEditorStore((s) => s.redo);
  const reset = useEditorStore((s) => s.reset);
  const setPlaying = useEditorStore((s) => s.setPlaying);
  const isPlaying = useEditorStore((s) => s.isPlaying);
  const channelEdit = useEditorStore((s) => s.channelEdit);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.code === "Space" && !isInputFocused()) {
        e.preventDefault();
        setPlaying(!isPlaying);
      }
      if (e.ctrlKey && e.code === "KeyZ" && !e.shiftKey) {
        e.preventDefault();
        if (canUndo) undo();
      }
      if (e.ctrlKey && (e.code === "KeyY" || (e.code === "KeyZ" && e.shiftKey))) {
        e.preventDefault();
        if (canRedo) redo();
      }
      if (e.code === "Escape" && !isInputFocused()) {
        useEditorStore.getState().setSelection(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isPlaying, canUndo, canRedo, undo, redo, setPlaying]);

  if (!asset) return null;

  return (
    <div className="flex items-center justify-between px-4 py-3 bg-slate-800 border-b border-slate-700">
      <div className="flex items-center gap-3">
        <button
          onClick={reset}
          disabled={!!channelEdit}
          className="toolbar-btn"
          title="Upload a new file"
        >
          New File
        </button>
        <div className="w-px h-6 bg-slate-600 mx-1" />
        <span className="text-sm font-medium text-slate-300 truncate max-w-xs">
          {channelEdit
            ? `Channel Edit: ${channelEdit.activeChannel === "left" ? "Left" : "Right"}`
            : `${asset.sampleRate}Hz / ${asset.channels === 2 ? "Stereo" : "Mono"}${asset.durationSec ? ` / ${asset.durationSec.toFixed(1)}s` : ""}`
          }
        </span>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={undo}
          disabled={!canUndo || !!channelEdit}
          className="toolbar-btn"
          title="Undo (Ctrl+Z)"
        >
          Undo
        </button>
        <button
          onClick={redo}
          disabled={!canRedo || !!channelEdit}
          className="toolbar-btn"
          title="Redo (Ctrl+Shift+Z)"
        >
          Redo
        </button>
        <div className="w-px h-6 bg-slate-600 mx-1" />
        <ExportPopover />
      </div>
    </div>
  );
}

function isInputFocused(): boolean {
  const el = document.activeElement;
  return el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement;
}
