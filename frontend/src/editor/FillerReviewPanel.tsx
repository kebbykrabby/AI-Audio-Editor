import { useMemo, useRef, useState } from "react";
import { ApiRequestError } from "../api/client";
import { enqueueOperation, pollOperation } from "../api/operations";
import { useEditorStore } from "../store/editorStore";
import type { FillerRegion } from "../store/types";

/**
 * Review mode for AI-detected filler regions.
 *
 * The confidence slider acts as a pre-commit filter: regions below threshold
 * are grayed and excluded unless the user explicitly re-accepts them by
 * toggling the checkbox. Regions above threshold are accepted by default and
 * can be rejected individually.
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
      const enqueued = await enqueueOperation(
        "remove_segments",
        review.inputAssetId,
        {
          intervals: accepted.map((r) => ({ start: r.start, end: r.end })),
          crossfade_ms: 20,
        },
      );
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
      setError(
        e instanceof Error ? e.message : "Failed to remove selected regions",
      );
    } finally {
      setCommitting(false);
      setPendingOperation(null);
      abortRef.current = null;
    }
  };

  return (
    <div className="border border-slate-700 rounded bg-slate-900 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">
            Review filler words
          </h3>
          <p className="text-xs text-slate-400">
            {accepted.length} of {total} selected
            {review.result.modelVersion && (
              <> · model: {review.result.modelVersion}</>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={exitReview}
            disabled={committing}
            className="op-btn"
            title="Discard detection and return to the editor"
          >
            Cancel
          </button>
          <button
            onClick={handleCommit}
            disabled={committing || isProcessing || accepted.length === 0}
            className="op-btn"
            title="Remove all currently-selected regions"
          >
            {committing
              ? "Removing…"
              : `Remove ${accepted.length} region${accepted.length === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <label className="text-xs text-slate-500">Confidence floor</label>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={review.confidenceThreshold}
          onChange={(e) => setThreshold(Number(e.target.value))}
          className="w-56"
          disabled={committing}
        />
        <span className="text-xs text-slate-300 w-10">
          {review.confidenceThreshold.toFixed(2)}
        </span>
      </div>

      {total === 0 ? (
        <p className="text-sm text-slate-400">
          No filler words detected in this audio.
        </p>
      ) : (
        <ul className="max-h-96 overflow-y-auto divide-y divide-slate-800 border border-slate-800 rounded">
          {regions.map((r) => {
            const rejected = review.rejectedWordIndices.has(r.wordIndex);
            const belowFloor = r.confidence < review.confidenceThreshold;
            const isAccepted = !belowFloor && !rejected;
            return (
              <li
                key={r.wordIndex}
                className={`flex items-center gap-2 px-2 py-1.5 text-sm ${
                  isAccepted ? "bg-slate-900" : "bg-slate-900/40 text-slate-500"
                }`}
              >
                <button
                  type="button"
                  onClick={() => playRange(r.start, r.end)}
                  disabled={committing}
                  className="px-1.5 text-slate-400 hover:text-slate-100 disabled:opacity-40"
                  aria-label={`Preview region at ${r.start.toFixed(2)}s`}
                  title="Preview this segment"
                >
                  ▶
                </button>
                <input
                  type="checkbox"
                  checked={isAccepted}
                  disabled={committing || belowFloor}
                  onChange={() => toggleReject(r.wordIndex)}
                  aria-label={`Toggle region at ${r.start.toFixed(2)}s`}
                />
                <span className="font-mono text-xs text-slate-400 w-24 tabular-nums">
                  {formatTime(r.start)}–{formatTime(r.end)}
                </span>
                <span className="flex-1 truncate">{r.text}</span>
                <span className="text-xs uppercase tracking-wide text-slate-500 w-20">
                  {r.category}
                </span>
                <span className="text-xs text-slate-400 w-12 text-right">
                  {(r.confidence * 100).toFixed(0)}%
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec - m * 60;
  return `${m}:${s.toFixed(2).padStart(5, "0")}`;
}
