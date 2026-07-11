import { useEffect, useRef, useCallback, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin, { type Region } from "wavesurfer.js/dist/plugins/regions.js";
import { Pause, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatTime } from "@/lib/time";
import { useEditorStore } from "../store/editorStore";
import { useAssetUrlRefresh } from "./useAssetUrlRefresh";

/**
 * Read a `--foo` HSL-parts variable (e.g. "250 65% 55%") from :root and
 * wrap it in `hsl(...)` for WaveSurfer, which needs a full color string.
 * `fallback` is used if the variable isn't set (e.g. during SSR or tests).
 */
function readThemeColor(varName: string, fallback: string, alpha?: number): string {
  if (typeof window === "undefined") return fallback;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
  if (!raw) return fallback;
  return alpha != null ? `hsl(${raw} / ${alpha})` : `hsl(${raw})`;
}

const FILLER_REGION_ID_PREFIX = "filler-";
const PROFANITY_REGION_ID_PREFIX = "profanity-";
const NLE_REGION_ID_PREFIX = "nle-";

interface NleStepLike {
  stepIndex: number;
  operation: { type: string; parameters: Record<string, unknown> };
  validationStatus: "valid" | "invalid";
}

/**
 * Time range an NLE step affects, or null if the step touches the whole asset.
 * Anchors fade_out against the asset duration so the overlay paints the tail
 * end, not the start.
 */
function nleStepRange(step: NleStepLike, assetDuration: number): [number, number] | null {
  const p = step.operation.parameters || {};
  const num = (k: string) => (typeof p[k] === "number" ? (p[k] as number) : null);
  switch (step.operation.type) {
    case "trim":
    case "delete":
    case "reverse_range":
    case "gain_range": {
      const s = num("start_sec");
      const e = num("end_sec");
      return s !== null && e !== null && e > s ? [s, e] : null;
    }
    case "fade_in": {
      const d = num("duration_sec");
      return d !== null && d > 0 ? [0, d] : null;
    }
    case "fade_out": {
      const d = num("duration_sec");
      if (d === null || d <= 0 || assetDuration <= 0) return null;
      return [Math.max(0, assetDuration - d), assetDuration];
    }
    // remove_silence / reverse / gain / normalize / speed / channel ops
    // affect the whole asset → no localized overlay.
    default:
      return null;
  }
}

export default function WaveformPlayer() {
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const regionsRef = useRef<RegionsPlugin | null>(null);
  const regionRef = useRef<Region | null>(null);
  const fillerRegionsRef = useRef<Region[]>([]);
  const profanityRegionsRef = useRef<Region[]>([]);
  const nleRegionsRef = useRef<Region[]>([]);
  const skipSyncRef = useRef(false);
  const [isLoading, setIsLoading] = useState(true);

  const asset = useEditorStore((s) => s.currentAsset());
  const setPlaying = useEditorStore((s) => s.setPlaying);
  const setCurrentTime = useEditorStore((s) => s.setCurrentTime);
  const setSelection = useEditorStore((s) => s.setSelection);
  const selection = useEditorStore((s) => s.selection);
  const isPlaying = useEditorStore((s) => s.isPlaying);
  const currentTimeSec = useEditorStore((s) => s.currentTimeSec);
  const playbackRequest = useEditorStore((s) => s.playbackRequest);
  const activeFillerReview = useEditorStore((s) => s.activeFillerReview);
  const activeProfanityReview = useEditorStore((s) => s.activeProfanityReview);
  const activeNlePlanReview = useEditorStore((s) => s.activeNlePlanReview);

  // Pre-emptive URL refresh so signed URLs don't expire mid-session.
  // Also exposes refreshNow() for media-error recovery.
  const { refreshNow } = useAssetUrlRefresh(asset?.assetId ?? null);
  const recoveringRef = useRef(false);

  // Initialize WaveSurfer
  useEffect(() => {
    if (!containerRef.current || !asset?.audioUrl) return;

    const regions = RegionsPlugin.create();
    regionsRef.current = regions;

    // Read theme colors from CSS vars so re-tinting the app doesn't need a
    // rebuild of the waveform. Alpha lets the progress bar sit visually on top
    // of the wave (same hue, higher saturation) without a second variable.
    const waveColor = readThemeColor("--primary", "#4f83cc", 0.45);
    const progressColor = readThemeColor("--primary", "#1d4ed8");
    const cursorColor = readThemeColor("--foreground", "#f59e0b", 0.75);

    const ws = WaveSurfer.create({
      container: containerRef.current,
      height: 180,
      waveColor,
      progressColor,
      cursorColor,
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
    // If the browser rejects the media (most likely a 403 from an expired
    // signed URL), request a fresh asset. The store update rotates audioUrl,
    // which re-triggers the init effect above and reloads WaveSurfer.
    ws.on("error", () => {
      if (recoveringRef.current) return;
      recoveringRef.current = true;
      void refreshNow().finally(() => {
        recoveringRef.current = false;
      });
    });

    // Region selection — use the theme's primary hue so the drag-to-select
    // overlay matches the waveform without an extra token.
    const selectionColor = readThemeColor("--primary", "rgba(59,130,246,0.3)", 0.25);
    regions.enableDragSelection({ color: selectionColor });
    const isAiOverlay = (id: string) =>
      id.startsWith(FILLER_REGION_ID_PREFIX) ||
      id.startsWith(PROFANITY_REGION_ID_PREFIX) ||
      id.startsWith(NLE_REGION_ID_PREFIX);

    regions.on("region-created", (region) => {
      // AI-detected overlays are owned by their effects (below); they must not
      // be treated as the user's drag-selection.
      if (isAiOverlay(region.id)) return;
      // Remove previous selection region
      if (regionRef.current && regionRef.current.id !== region.id) {
        regionRef.current.remove();
      }
      regionRef.current = region;
      skipSyncRef.current = true;
      setSelection({ startSec: region.start, endSec: region.end });
    });
    regions.on("region-updated", (region) => {
      if (isAiOverlay(region.id)) return;
      regionRef.current = region;
      skipSyncRef.current = true;
      setSelection({ startSec: region.start, endSec: region.end });
    });
    // Clicking an AI-overlay region previews the snippet (same as the ▶ button
    // in the matching review panel). Use store.getState() so the handler
    // captures the latest action even though it was registered once at mount.
    regions.on("region-clicked", (region, e) => {
      if (!isAiOverlay(region.id)) return;
      e.stopPropagation();
      useEditorStore.getState().playRange(region.start, region.end);
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

  // Play a single range on demand (filler-region preview). The `id` field
  // changes on every request so identical (start,end) repeats still fire.
  useEffect(() => {
    const ws = wsRef.current;
    if (!ws || !playbackRequest) return;
    ws.setTime(playbackRequest.startSec);
    ws.play().catch(() => {});
    const lengthMs = Math.max(0, playbackRequest.endSec - playbackRequest.startSec) * 1000;
    const timer = window.setTimeout(() => {
      if (wsRef.current?.isPlaying()) wsRef.current.pause();
    }, lengthMs + 50);
    return () => window.clearTimeout(timer);
  }, [playbackRequest?.id]);

  // Draw the AI-detected filler regions as colored overlays on the waveform.
  // Wipe-and-redraw on every relevant state change (review enter/exit,
  // confidence-threshold change, accept/reject toggle) — region counts are
  // small enough (< low hundreds) that diffing isn't worth the complexity.
  useEffect(() => {
    const regions = regionsRef.current;
    if (!regions) return;
    // Cleanup previous overlays.
    for (const r of fillerRegionsRef.current) {
      try { r.remove(); } catch { /* already removed */ }
    }
    fillerRegionsRef.current = [];
    if (!activeFillerReview) return;
    const { result, confidenceThreshold, rejectedWordIndices } = activeFillerReview;
    for (const r of result.regions) {
      const accepted =
        r.confidence >= confidenceThreshold &&
        !rejectedWordIndices.has(r.wordIndex);
      const color = accepted
        ? "rgba(239, 68, 68, 0.35)"   // red-500/35 — about-to-be-cut
        : "rgba(100, 116, 139, 0.15)"; // slate-500/15 — inactive
      const region = regions.addRegion({
        id: `${FILLER_REGION_ID_PREFIX}${r.wordIndex}`,
        start: r.start,
        end: r.end,
        color,
        drag: false,
        resize: false,
      });
      fillerRegionsRef.current.push(region);
    }
  }, [activeFillerReview]);

  // Same idea for profanity overlays — different ID prefix, different color
  // (orange) so red filler overlays and orange profanity overlays would be
  // visually distinguishable if both were ever shown simultaneously. In
  // practice only one panel is mounted at a time via Shell's switch.
  useEffect(() => {
    const regions = regionsRef.current;
    if (!regions) return;
    for (const r of profanityRegionsRef.current) {
      try { r.remove(); } catch { /* already removed */ }
    }
    profanityRegionsRef.current = [];
    if (!activeProfanityReview) return;
    const { result, confidenceThreshold, rejectedWordIndices } = activeProfanityReview;
    for (const r of result.regions) {
      const accepted =
        r.confidence >= confidenceThreshold &&
        !rejectedWordIndices.has(r.wordIndex);
      const color = accepted
        ? "rgba(249, 115, 22, 0.35)"   // orange-500/35 — about-to-be-censored
        : "rgba(100, 116, 139, 0.15)"; // slate-500/15 — inactive
      const region = regions.addRegion({
        id: `${PROFANITY_REGION_ID_PREFIX}${r.wordIndex}`,
        start: r.start,
        end: r.end,
        color,
        drag: false,
        resize: false,
      });
      profanityRegionsRef.current.push(region);
    }
  }, [activeProfanityReview]);

  // NLE plan overlays — blue, distinct from red (fillers) and orange
  // (profanity). One overlay per step whose params encode a time range
  // (trim, delete, fade_in, fade_out, remove_silence). Other ops (reverse,
  // gain, normalize, speed, channel ops) touch the whole asset and don't
  // get a localized overlay; they live in the side-panel list only.
  useEffect(() => {
    const regions = regionsRef.current;
    if (!regions) return;
    for (const r of nleRegionsRef.current) {
      try { r.remove(); } catch { /* already removed */ }
    }
    nleRegionsRef.current = [];
    if (!activeNlePlanReview) return;

    const assetDuration = asset?.durationSec ?? 0;
    const { result, excludedStepIndices } = activeNlePlanReview;

    for (const step of result.steps) {
      const range = nleStepRange(step, assetDuration);
      if (!range) continue;
      const isEnabled =
        step.validationStatus === "valid" &&
        !excludedStepIndices.has(step.stepIndex);
      const color = isEnabled
        ? "rgba(59, 130, 246, 0.30)"   // blue-500/30 — about-to-be-applied
        : "rgba(100, 116, 139, 0.15)"; // slate-500/15 — inactive
      const region = regions.addRegion({
        id: `${NLE_REGION_ID_PREFIX}${step.stepIndex}`,
        start: range[0],
        end: range[1],
        color,
        drag: false,
        resize: false,
      });
      nleRegionsRef.current.push(region);
    }
  }, [activeNlePlanReview, asset?.durationSec]);

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
        color: readThemeColor("--primary", "rgba(59,130,246,0.3)", 0.25),
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
      <div className="relative rounded-xl border border-border bg-card overflow-hidden">
        <div
          ref={containerRef}
          className="waveform-canvas w-full"
        />
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-card/80 backdrop-blur-sm">
            <span className="text-sm text-muted-foreground">Loading waveform…</span>
          </div>
        )}
      </div>
      <div className="flex items-center gap-3 mt-3">
        <Button onClick={togglePlay} size="sm" className="gap-1.5">
          {isPlaying ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
          {isPlaying ? "Pause" : "Play"}
        </Button>
        <span className="text-sm text-muted-foreground font-mono">
          {formatTime(currentTimeSec)} / {formatTime(asset?.durationSec ?? 0)}
        </span>
      </div>
    </div>
  );
}
