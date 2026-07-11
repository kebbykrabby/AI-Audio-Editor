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
        pushAsset(completed.asset, durationChanged);
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
    <div className="rounded-lg border border-border bg-card p-4 space-y-4 shadow-sm">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-1.5">
            <ShieldAlert className="w-3.5 h-3.5 text-primary" />
            Review profanity
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {accepted.length} of {total} selected
            {review.result.modelVersion && <> · model: {review.result.modelVersion}</>}
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={exitReview}
            disabled={committing}
            title="Discard detection and return to the editor"
          >
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleCommit}
            disabled={committing || isProcessing || accepted.length === 0}
            title="Censor all currently-selected regions"
          >
            {committing
              ? "Censoring…"
              : `Censor ${accepted.length} word${accepted.length === 1 ? "" : "s"}`}
          </Button>
        </div>
      </div>

      {/* Mode selector */}
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] items-end">
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
              Frequency (Hz)
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
              className="mt-1 w-28"
            />
          </div>
        )}
      </div>
      <p className="text-xs text-muted-foreground italic -mt-2">
        {MODE_DESCRIPTIONS[review.mode]}
      </p>

      {/* Confidence slider — hidden when every match was exact */}
      {hasNonExactMatches && (
        <div className="flex items-center gap-3">
          <label className="text-xs text-muted-foreground w-24 shrink-0">
            Confidence floor
          </label>
          <Slider
            min={0}
            max={1}
            step={0.05}
            value={[review.confidenceThreshold]}
            onValueChange={([v]) => setThreshold(v)}
            disabled={committing}
            className="max-w-xs"
          />
          <span className="text-xs font-mono text-foreground w-10 text-right">
            {review.confidenceThreshold.toFixed(2)}
          </span>
        </div>
      )}

      {/* Region list */}
      {total === 0 ? (
        <p className="text-sm text-muted-foreground">No profanity detected in this audio.</p>
      ) : (
        <ScrollArea className="max-h-96 rounded-md border border-border">
          <ul className="divide-y divide-border">
            {regions.map((r) => {
              const rejected = review.rejectedWordIndices.has(r.wordIndex);
              const belowFloor = r.confidence < review.confidenceThreshold;
              const isAccepted = !belowFloor && !rejected;
              return (
                <li
                  key={r.wordIndex}
                  className={`flex items-center gap-2 px-2 py-1.5 text-sm transition-colors ${
                    isAccepted ? "bg-background" : "bg-muted/40 text-muted-foreground"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => playRange(r.start, r.end)}
                    disabled={committing}
                    className="flex items-center justify-center w-6 h-6 rounded hover:bg-accent text-muted-foreground hover:text-foreground disabled:opacity-40"
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
                  <span className="font-mono text-xs text-muted-foreground w-28 tabular-nums">
                    {formatTime(r.start)}–{formatTime(r.end)}
                  </span>
                  <span className="flex-1 truncate">{r.text}</span>
                  <span className="text-xs uppercase tracking-wide text-muted-foreground w-20">
                    {r.matchedBy}
                  </span>
                  <span className="text-xs font-mono text-muted-foreground w-12 text-right">
                    {(r.confidence * 100).toFixed(0)}%
                  </span>
                </li>
              );
            })}
          </ul>
        </ScrollArea>
      )}
    </div>
  );
}
