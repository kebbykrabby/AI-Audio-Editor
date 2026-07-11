import { useEffect, useState } from "react";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatTime, parseTime } from "@/lib/time";
import { useEditorStore } from "../store/editorStore";

/**
 * Horizontal transport strip below the waveform. Combines:
 *   - Play / Pause / skip 5s
 *   - Current time / total duration (mono)
 *   - Editable selection start / end (numeric inputs, absorbed from the old
 *     SelectionInfo component)
 *
 * All state comes from `editorStore`. This component owns no playback state
 * itself — WaveformPlayer syncs against `isPlaying` and the store.
 */
export default function TransportBar() {
  const asset = useEditorStore((s) => s.currentAsset());
  const isPlaying = useEditorStore((s) => s.isPlaying);
  const setPlaying = useEditorStore((s) => s.setPlaying);
  const currentTimeSec = useEditorStore((s) => s.currentTimeSec);
  const setCurrentTime = useEditorStore((s) => s.setCurrentTime);
  const selection = useEditorStore((s) => s.selection);
  const setSelection = useEditorStore((s) => s.setSelection);

  const duration = asset?.durationSec ?? 0;

  // Local text state for the selection inputs so users can type "1.2" without
  // the store rewriting it every keystroke.
  const [startText, setStartText] = useState("");
  const [endText, setEndText] = useState("");

  useEffect(() => {
    if (selection) {
      setStartText(formatTime(selection.startSec));
      setEndText(formatTime(selection.endSec));
    } else {
      setStartText("");
      setEndText("");
    }
  }, [selection?.startSec, selection?.endSec, selection]);

  if (!asset) return null;

  const commitStart = (raw: string) => {
    if (!selection) return;
    const n = parseTime(raw);
    if (Number.isNaN(n) || n < 0 || n >= selection.endSec) {
      setStartText(formatTime(selection.startSec));
      return;
    }
    setSelection({ startSec: n, endSec: selection.endSec });
  };
  const commitEnd = (raw: string) => {
    if (!selection) return;
    const n = parseTime(raw);
    if (Number.isNaN(n) || n <= selection.startSec || n > duration) {
      setEndText(formatTime(selection.endSec));
      return;
    }
    setSelection({ startSec: selection.startSec, endSec: n });
  };

  const nudge = (deltaSec: number) => {
    setCurrentTime(Math.max(0, Math.min(duration, currentTimeSec + deltaSec)));
  };

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card px-3 py-2 shadow-sm">
      {/* Transport controls */}
      <div className="flex items-center gap-1">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => nudge(-5)}
          title="Skip back 5s"
        >
          <SkipBack className="w-4 h-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          className="h-9 w-9"
          onClick={() => setPlaying(!isPlaying)}
          title={isPlaying ? "Pause (Space)" : "Play (Space)"}
        >
          {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => nudge(5)}
          title="Skip forward 5s"
        >
          <SkipForward className="w-4 h-4" />
        </Button>
      </div>

      {/* Time readout */}
      <div className="text-sm font-mono text-muted-foreground">
        <span className="text-foreground">{formatTime(currentTimeSec)}</span>
        <span className="mx-1 opacity-50">/</span>
        <span>{formatTime(duration)}</span>
      </div>

      <div className="flex-1" />

      {/* Selection editor — only when there's an active selection */}
      {selection ? (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-xs uppercase tracking-wide text-muted-foreground">Sel</span>
          <Input
            value={startText}
            onChange={(e) => setStartText(e.target.value)}
            onBlur={(e) => commitStart(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && commitStart(e.currentTarget.value)}
            className="h-8 w-24 font-mono text-xs"
            aria-label="Selection start"
          />
          <span className="text-xs text-muted-foreground">to</span>
          <Input
            value={endText}
            onChange={(e) => setEndText(e.target.value)}
            onBlur={(e) => commitEnd(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && commitEnd(e.currentTarget.value)}
            className="h-8 w-24 font-mono text-xs"
            aria-label="Selection end"
          />
          <span className="text-xs text-muted-foreground font-mono">
            ({(selection.endSec - selection.startSec).toFixed(2)}s)
          </span>
        </div>
      ) : (
        <span className="text-xs text-muted-foreground">
          Drag on the waveform to select a range
        </span>
      )}
    </div>
  );
}
