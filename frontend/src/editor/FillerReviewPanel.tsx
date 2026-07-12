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
        pushAsset(
          completed.asset,
          /* durationChanged */ true,
          `Removed ${accepted.length} filler word${accepted.length === 1 ? "" : "s"}`,
        );
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
    <div className="rounded-lg border border-border bg-card shadow-sm flex flex-col h-full overflow-hidden">
      {/* Fixed header — title + meta */}
      <div className="p-3 border-b border-border shrink-0 space-y-1.5">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-1.5">
          <Sparkles className="w-3.5 h-3.5 text-primary" />
          Review filler words
        </h3>
        <p className="text-xs text-muted-foreground">
          {accepted.length} of {total} selected
        </p>
      </div>

      {/* Fixed confidence slider */}
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

      {/* Scrollable region list — flex-1 min-h-0 gives it the leftover height. */}
      {total === 0 ? (
        <p className="text-sm text-muted-foreground p-3">
          No filler words detected in this audio.
        </p>
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
                    <span className="uppercase tracking-wide">{r.category}</span>
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
          title="Discard detection and return to the editor"
        >
          Cancel
        </Button>
        <Button
          size="sm"
          onClick={handleCommit}
          disabled={committing || isProcessing || accepted.length === 0}
          className="flex-1"
          title="Remove all currently-selected regions"
        >
          {committing ? "Removing…" : `Remove ${accepted.length}`}
        </Button>
      </div>
    </div>
  );
}
