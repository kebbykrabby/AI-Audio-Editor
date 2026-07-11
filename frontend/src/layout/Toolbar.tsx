import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useEditorStore } from "../store/editorStore";
import ExportPopover from "./ExportPopover";

export default function Toolbar() {
  const navigate = useNavigate();
  const asset = useEditorStore((s) => s.currentAsset());
  const canUndo = useEditorStore((s) => s.canUndo());
  const canRedo = useEditorStore((s) => s.canRedo());
  const undo = useEditorStore((s) => s.undo);
  const redo = useEditorStore((s) => s.redo);
  const reset = useEditorStore((s) => s.reset);
  const setPlaying = useEditorStore((s) => s.setPlaying);
  const isPlaying = useEditorStore((s) => s.isPlaying);
  const channelEdit = useEditorStore((s) => s.channelEdit);

  const handleNewFile = () => {
    // Wipe editor state, then hop over to the Dashboard where the user can
    // upload a fresh file or pick a project.
    reset();
    navigate("/");
  };

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
    <div className="flex items-center gap-2 min-w-0">
      <button
        onClick={handleNewFile}
        disabled={!!channelEdit}
        className="toolbar-btn"
        title="Back to projects"
      >
        Projects
      </button>
      <div className="w-px h-5 bg-border mx-1" />
      <span className="text-xs font-medium text-muted-foreground truncate">
        {channelEdit
          ? `Channel Edit: ${channelEdit.activeChannel === "left" ? "Left" : "Right"}`
          : `${asset.sampleRate}Hz · ${asset.channels === 2 ? "Stereo" : "Mono"}${asset.durationSec ? ` · ${asset.durationSec.toFixed(1)}s` : ""}`
        }
      </span>
      <div className="flex-1" />
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
      <div className="w-px h-5 bg-border mx-1" />
      <ExportPopover />
    </div>
  );
}

function isInputFocused(): boolean {
  const el = document.activeElement;
  return el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement;
}
