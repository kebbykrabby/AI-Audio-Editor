import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Redo2, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useEditorStore } from "../store/editorStore";
import ExportPopover from "./ExportPopover";

/**
 * Header toolbar mounted in Shell. Owns the New-file / Undo / Redo / Export
 * controls + global keyboard shortcuts (Space, Ctrl+Z, Ctrl+Y, Escape).
 */
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
    reset();
    navigate("/");
  };

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
      <Button
        variant="ghost"
        size="sm"
        className="h-8 gap-1.5"
        disabled={!!channelEdit}
        onClick={handleNewFile}
        title="Back to projects"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">Projects</span>
      </Button>
      <div className="w-px h-5 bg-border mx-1" />
      <span className="text-xs font-medium text-muted-foreground truncate font-mono">
        {channelEdit
          ? `Channel Edit: ${channelEdit.activeChannel === "left" ? "Left" : "Right"}`
          : `${asset.sampleRate}Hz · ${asset.channels === 2 ? "Stereo" : "Mono"}${asset.durationSec ? ` · ${asset.durationSec.toFixed(1)}s` : ""}`}
      </span>
      <div className="flex-1" />
      <Button
        variant="ghost"
        size="icon"
        className="h-8 w-8"
        onClick={undo}
        disabled={!canUndo || !!channelEdit}
        title="Undo (Ctrl+Z)"
      >
        <Undo2 className="w-4 h-4" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="h-8 w-8"
        onClick={redo}
        disabled={!canRedo || !!channelEdit}
        title="Redo (Ctrl+Shift+Z)"
      >
        <Redo2 className="w-4 h-4" />
      </Button>
      <div className="w-px h-5 bg-border mx-1" />
      <ExportPopover />
    </div>
  );
}

function isInputFocused(): boolean {
  const el = document.activeElement;
  return (
    el instanceof HTMLInputElement ||
    el instanceof HTMLSelectElement ||
    el instanceof HTMLTextAreaElement
  );
}
