import { useMemo, useRef, useState } from "react";
import { Play, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Slider } from "@/components/ui/slider";
import { formatTime } from "@/lib/time";
import { ApiRequestError } from "../api/client";
import { enqueueOperation, pollOperation } from "../api/operations";
import { useEditorStore } from "../store/editorStore";
import type { FillerRegion } from "../store/types";

/**
 * Review mode for AI-detected filler regions.
 *
 * The confidence slider acts as a pre-commit filter: regions below the
 * threshold are grayed and excluded unless the user explicitly re-accepts
 * them by toggling the checkbox. Regions above threshold are accepted by
 * default and can be rejected individually.
 *
 * On commit, enqueues `remove_segments` with the accepted intervals + a
 * short crossfade, and pushes the resulting derived asset onto history.
 */
export default function FillerReviewPanel() {
  const asset = useEditorStore((s) => s.currentAsset());
  const review = useEditorStore((s) => s.activeFillerReview);
  const toggleReject = useEditorStore((s) => s.toggleFillerReject);
  const setThreshold = useEditorStore((s) => s.setFillerConfidenceThreshold);
  const exitReview = useEditorStore((s) => s.exitFillerReview);
  const pushAsset = useEditorStore((s) => s.pushAsset);
  const setPendingOperation = useEditorStore((s) => s.setPendingOperation);
  const setError = useEditorStore((s) => s.setError);
  const isProcessing = useEditorStore((s) => s.isProcessing);
  const playRange = useEditorStore((s) => s.playRange);

  const [committing, setCommitting] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const accepted = useMemo<FillerRegion[]>(() => {
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

  const handleCommit = async () => {
    if (accepted.length === 0) {
      setError("Select at least one region to remove.");
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setCommitting(true);
    setError(null);

    try {
      const enqueued = await enqueueOperation("remove_segments", review.inputAssetId, {
        intervals: accepted.map((r) => ({ start: r.start, end: r.end })),
        crossfade_ms: 20,
      });
      setPendingOperation({
        operationId: enqueued.operationId,
        type: "remove_segments",
        inputAssetId: review.inputAssetId,
        startedAt: Date.now(),
      });
      const completed = await pollOperation(enqueued.operationId, {
        signal: controller.signal,
      });
      if (completed.asset) {
        pushAsset(completed.asset, /* durationChanged */ true);
      }
      exitReview();
    } catch (e) {
      if (e instanceof ApiRequestError && e.code === "ABORTED") return;
      setError(e instanceof Error ? e.message : "Failed to remove selected regions");
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
            <Sparkles className="w-3.5 h-3.5 text-primary" />
            Review filler words
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
            title="Remove all currently-selected regions"
          >
            {committing
              ? "Removing…"
              : `Remove ${accepted.length} region${accepted.length === 1 ? "" : "s"}`}
          </Button>
        </div>
      </div>

      {/* Confidence slider */}
      <div className="flex items-center gap-3">
        <label className="text-xs text-muted-foreground w-24 shrink-0">Confidence floor</label>
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

      {/* Region list */}
      {total === 0 ? (
        <p className="text-sm text-muted-foreground">
          No filler words detected in this audio.
        </p>
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
                    {r.category}
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
