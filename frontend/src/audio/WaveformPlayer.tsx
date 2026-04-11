import { useEffect, useRef, useCallback, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin, { type Region } from "wavesurfer.js/dist/plugins/regions.js";
import { useEditorStore } from "../store/editorStore";

export default function WaveformPlayer() {
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const regionsRef = useRef<RegionsPlugin | null>(null);
  const regionRef = useRef<Region | null>(null);
  const skipSyncRef = useRef(false);
  const [isLoading, setIsLoading] = useState(true);

  const asset = useEditorStore((s) => s.currentAsset());
  const setPlaying = useEditorStore((s) => s.setPlaying);
  const setCurrentTime = useEditorStore((s) => s.setCurrentTime);
  const setSelection = useEditorStore((s) => s.setSelection);
  const selection = useEditorStore((s) => s.selection);
  const isPlaying = useEditorStore((s) => s.isPlaying);
  const currentTimeSec = useEditorStore((s) => s.currentTimeSec);

  // Initialize WaveSurfer
  useEffect(() => {
    if (!containerRef.current || !asset?.audioUrl) return;

    const regions = RegionsPlugin.create();
    regionsRef.current = regions;

    const ws = WaveSurfer.create({
      container: containerRef.current,
      height: 180,
      waveColor: "#4f83cc",
      progressColor: "#1d4ed8",
      cursorColor: "#f59e0b",
      cursorWidth: 2,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      plugins: [regions],
    });

    // Load audio with pre-computed peaks if available
    if (asset.waveformUrl && asset.durationSec) {
      fetch(asset.waveformUrl)
        .then((r) => r.json())
        .then((peaks: number[]) => {
          ws.load(asset.audioUrl!, [peaks], asset.durationSec!);
        })
        .catch(() => {
          ws.load(asset.audioUrl!);
        });
    } else {
      ws.load(asset.audioUrl!);
    }

    setIsLoading(true);
    ws.on("ready", () => setIsLoading(false));
    ws.on("play", () => setPlaying(true));
    ws.on("pause", () => setPlaying(false));
    ws.on("timeupdate", (time) => setCurrentTime(time));

    // Region selection
    regions.enableDragSelection({ color: "rgba(59, 130, 246, 0.3)" });
    regions.on("region-created", (region) => {
      // Remove previous selection region
      if (regionRef.current && regionRef.current.id !== region.id) {
        regionRef.current.remove();
      }
      regionRef.current = region;
      skipSyncRef.current = true;
      setSelection({ startSec: region.start, endSec: region.end });
    });
    regions.on("region-updated", (region) => {
      regionRef.current = region;
      skipSyncRef.current = true;
      setSelection({ startSec: region.start, endSec: region.end });
    });

    wsRef.current = ws;

    return () => {
      ws.destroy();
      wsRef.current = null;
      regionsRef.current = null;
      regionRef.current = null;
    };
  }, [asset?.assetId, asset?.audioUrl, asset?.waveformUrl]);

  // Sync play/pause from store
  useEffect(() => {
    const ws = wsRef.current;
    if (!ws) return;
    if (isPlaying && !ws.isPlaying()) ws.play().catch(() => {});
    if (!isPlaying && ws.isPlaying()) ws.pause();
  }, [isPlaying]);

  // Sync selection from store (e.g. numeric input changes)
  useEffect(() => {
    if (skipSyncRef.current) {
      skipSyncRef.current = false;
      return;
    }
    if (!regionsRef.current) return;
    if (!selection) {
      regionRef.current?.remove();
      regionRef.current = null;
      return;
    }
    if (regionRef.current) {
      regionRef.current.setOptions({ start: selection.startSec, end: selection.endSec });
    } else {
      regionRef.current = regionsRef.current.addRegion({
        start: selection.startSec,
        end: selection.endSec,
        color: "rgba(59, 130, 246, 0.3)",
        drag: true,
        resize: true,
      });
    }
  }, [selection?.startSec, selection?.endSec]);

  const togglePlay = useCallback(() => {
    wsRef.current?.playPause();
  }, []);

  return (
    <div>
      <div className="relative">
        <div
          ref={containerRef}
          className="w-full rounded-lg bg-slate-900 border border-slate-700 cursor-crosshair"
        />
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-900/80 rounded-lg">
            <span className="text-sm text-slate-400">Loading waveform...</span>
          </div>
        )}
      </div>
      <div className="flex items-center gap-4 mt-3">
        <button
          onClick={togglePlay}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-white text-sm font-medium"
        >
          {isPlaying ? "Pause" : "Play"}
        </button>
        <span className="text-sm text-slate-400 font-mono">
          {formatTime(currentTimeSec)} / {formatTime(asset?.durationSec ?? 0)}
        </span>
      </div>
    </div>
  );
}

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}
