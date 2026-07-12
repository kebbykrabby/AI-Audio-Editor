import { useMemo, useRef, useState } from "react";
import { Play, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { formatTime } from "@/lib/time";
import { ApiRequestError } from "../api/client";
import { enqueueOperation, pollOperation } from "../api/operations";
import { useEditorStore } from "../store/editorStore";
import type { CensorMode, ProfanityRegion } from "../store/types";

const MODE_LABELS: Record<CensorMode, string> = {
  beep: "Beep (1 kHz tone)",
  mute: "Mute (silence)",
  cut: "Cut (remove + shorten)",
  reverse_pitch: "Reverse + pitch shift",
};

const MODE_DESCRIPTIONS: Record<CensorMode, string> = {
  beep: "Replace each word with a sine tone. Recognizable broadcast censorship.",
  mute: "Replace each word with silence. Less attention-grabbing.",
  cut: "Remove each word entirely. Output duration is shorter than input.",
  reverse_pitch:
    "Replace each word with a reversed, pitch-shifted version. Output stays the same length.",
};

/**
 * Review panel for AI-detected profanity regions.
 *
 * Sibling of FillerReviewPanel by deliberate copy-paste; the two panels
 * will diverge (mode selector here, but not in fillers) and the design doc
 * says to resist premature abstraction until a 3rd AI feature ships.
 *
 * On commit, enqueues `censor_segments` with the accepted intervals + chosen
 * mode; only `cut` mode changes duration.
 */
export default function ProfanityReviewPanel() {
  const asset = useEditorStore((s) => s.currentAsset());
  const review = useEditorStore((s) => s.activeProfanityReview);
  const toggleReject = useEditorStore((s) => s.toggleProfanityReject);
  const setMode = useEditorStore((s) => s.setProfanityMode);
  const setBeepHz = useEditorStore((s) => s.setProfanityBeepHz);
  const setThreshold = useEditorStore((s) => s.setProfanityConfidenceThreshold);
  const exitReview = useEditorStore((s) => s.exitProfanityReview);
  const pushAsset = useEditorStore((s) => s.pushAsset);
  const setPendingOperation = useEditorStore((s) => s.setPendingOperation);
  const setError = useEditorStore((s) => s.setError);
  const isProcessing = useEditorStore((s) => s.isProcessing);
  const playRange = useEditorStore((s) => s.playRange);

  const [committing, setCommitting] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const accepted = useMemo<ProfanityRegion[]>(() => {
    if (!review) return [];
    return review.result.regions.filter(
      (r) =>
        r.confidence >= review.confidenceThreshold &&
        !review.rejectedWordIndices.has(r.wordIndex),
    );
  }, [review]);

  if (!asset || !review) return null;

  const regions = review.result.regions;
  const total = regions.length;
  const hasNonExactMatches = regions.some((r) => r.matchedBy !== "exact");

  const handleCommit = async () => {
    if (accepted.length === 0) {
      setError("Select at least one region to censor.");
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setCommitting(true);
    setError(null);

    try {
      const enqueued = await enqueueOperation("censor_segments", review.inputAssetId, {
        intervals: accepted.map((r) => ({ start: r.start, end: r.end })),
        mode: review.mode,
        beep_hz: review.beepHz,
      });
      setPendingOperation({
        operationId: enqueued.operationId,
        type: "censor_segments",
        inputAssetId: review.inputAssetId,
        startedAt: Date.now(),
      });
      const completed = await pollOperation(enqueued.operationId, {
        signal: controller.signal,
      });
      if (completed.asset) {
        const durationChanged = review.mode === "cut";
        pushAsset(
          completed.asset,
          durationChanged,
          `Censored ${accepted.length} word${accepted.length === 1 ? "" : "s"} (${review.mode})`,
        );
      }
      exitReview();
    } catch (e) {
      if (e instanceof ApiRequestError && e.code === "ABORTED") return;
      setError(e instanceof Error ? e.message : "Failed to censor selected regions");
    } finally {
      setCommitting(false);
      setPendingOperation(null);
      abortRef.current = null;
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card shadow-sm flex flex-col h-full overflow-hidden">
      {/* Fixed header */}
      <div className="p-3 border-b border-border shrink-0 space-y-1.5">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-1.5">
          <ShieldAlert className="w-3.5 h-3.5 text-primary" />
          Review profanity
        </h3>
        <p className="text-xs text-muted-foreground">
          {accepted.length} of {total} selected
        </p>
      </div>

      {/* Fixed mode selector */}
      <div className="p-3 border-b border-border shrink-0 space-y-2">
        <div className="grid gap-2 grid-cols-[minmax(0,1fr)_auto] items-end">
          <div>
            <Label htmlFor="censor-mode" className="text-xs">
              Mode
            </Label>
            <Select
              value={review.mode}
              onValueChange={(v) => setMode(v as CensorMode)}
              disabled={committing}
            >
              <SelectTrigger className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(MODE_LABELS) as CensorMode[]).map((m) => (
                  <SelectItem key={m} value={m}>
                    {MODE_LABELS[m]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {review.mode === "beep" && (
            <div>
              <Label htmlFor="beep-hz" className="text-xs">
                Hz
              </Label>
              <Input
                id="beep-hz"
                type="number"
                min={200}
                max={8000}
                step={100}
                value={review.beepHz}
                onChange={(e) => setBeepHz(Number(e.target.value))}
                disabled={committing}
                className="mt-1 w-20"
              />
            </div>
          )}
        </div>
        <p className="text-xs text-muted-foreground italic">
          {MODE_DESCRIPTIONS[review.mode]}
        </p>
      </div>

      {/* Fixed confidence slider — hidden when every match was exact */}
      {hasNonExactMatches && (
        <div className="p-3 border-b border-border shrink-0 flex items-center gap-2">
          <label className="text-xs text-muted-foreground shrink-0">Floor</label>
          <Slider
            min={0}
            max={1}
            step={0.05}
            value={[review.confidenceThreshold]}
            onValueChange={([v]) => setThreshold(v)}
            disabled={committing}
            className="flex-1"
          />
          <span className="text-xs font-mono text-foreground w-8 text-right shrink-0">
            {review.confidenceThreshold.toFixed(2)}
          </span>
        </div>
      )}

      {/* Scrollable region list */}
      {total === 0 ? (
        <p className="text-sm text-muted-foreground p-3">No profanity detected in this audio.</p>
      ) : (
        <ScrollArea className="flex-1 min-h-0">
          <ul className="divide-y divide-border">
            {regions.map((r) => {
              const rejected = review.rejectedWordIndices.has(r.wordIndex);
              const belowFloor = r.confidence < review.confidenceThreshold;
              const isAccepted = !belowFloor && !rejected;
              return (
                <li
                  key={r.wordIndex}
                  className={`px-2 py-1.5 text-sm transition-colors ${
                    isAccepted ? "bg-background" : "bg-muted/40 text-muted-foreground"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => playRange(r.start, r.end)}
                      disabled={committing}
                      className="flex items-center justify-center w-6 h-6 rounded hover:bg-accent text-muted-foreground hover:text-foreground disabled:opacity-40 shrink-0"
                      aria-label={`Preview region at ${r.start.toFixed(2)}s`}
                      title="Preview this segment"
                    >
                      <Play className="w-3 h-3" />
                    </button>
                    <Checkbox
                      checked={isAccepted}
                      disabled={committing || belowFloor}
                      onCheckedChange={() => toggleReject(r.wordIndex)}
                      aria-label={`Toggle region at ${r.start.toFixed(2)}s`}
                    />
                    <span className="flex-1 min-w-0 break-words font-medium">
                      {r.text}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5 pl-8 text-[10px] text-muted-foreground font-mono">
                    <span className="tabular-nums">
                      {formatTime(r.start)}–{formatTime(r.end)}
                    </span>
                    <span className="uppercase tracking-wide">{r.matchedBy}</span>
                    <span className="ml-auto">{(r.confidence * 100).toFixed(0)}%</span>
                  </div>
                </li>
              );
            })}
          </ul>
        </ScrollArea>
      )}

      {/* Sticky action footer */}
      <div className="p-3 border-t border-border shrink-0 flex gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={exitReview}
          disabled={committing}
          className="flex-1"
        >
          Cancel
        </Button>
        <Button
          size="sm"
          onClick={handleCommit}
          disabled={committing || isProcessing || accepted.length === 0}
          className="flex-1"
        >
          {committing ? "Censoring…" : `Censor ${accepted.length}`}
        </Button>
      </div>
    </div>
  );
}
