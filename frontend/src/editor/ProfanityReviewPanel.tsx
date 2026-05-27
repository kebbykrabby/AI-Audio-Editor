import { useMemo, useRef, useState } from "react";
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
 * Review panel for AI-detected profanity regions. Sibling of FillerReviewPanel
 * by deliberate copy-paste: the two features will diverge in the UI (mode
 * selector here, but not in fillers) and the design doc explicitly says to
 * resist premature abstraction until a 3rd AI feature lands.
 *
 * Key differences from FillerReviewPanel:
 * - Action applies `censor_segments` (duration-preserving) instead of
 *   `remove_segments` (duration-shortening).
 * - Confidence slider is hidden in Phase 1 (D4): exact match = 1.0 always,
 *   slider is meaningless until phonetic matching ships in Phase 4.
 * - Mode selector for censor mode (Phase 1: beep only; Phase 2 widens).
 * - Region rows show `matchedBy` tag so the user can see how each match was
 *   caught (helpful once variants/phonetic matchers exist).
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
  // D4: show the confidence floor slider only when the detection produced any
  // non-exact match. Exact-only results have confidence=1.0 across the board
  // so the slider would do nothing.
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
      const enqueued = await enqueueOperation(
        "censor_segments",
        review.inputAssetId,
        {
          intervals: accepted.map((r) => ({ start: r.start, end: r.end })),
          mode: review.mode,
          // beep_hz is only meaningful for mode=beep; always send it, server ignores otherwise.
          beep_hz: review.beepHz,
        },
      );
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
        // Only cut mode changes audio duration; the others replace in place.
        const durationChanged = review.mode === "cut";
        pushAsset(completed.asset, durationChanged);
      }
      exitReview();
    } catch (e) {
      if (e instanceof ApiRequestError && e.code === "ABORTED") return;
      setError(
        e instanceof Error ? e.message : "Failed to censor selected regions",
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
            Review profanity
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
            title="Censor all currently-selected regions"
          >
            {committing
              ? "Censoring…"
              : `Censor ${accepted.length} word${accepted.length === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
        <label htmlFor="censor-mode" className="text-slate-400">Mode</label>
        <select
          id="censor-mode"
          value={review.mode}
          onChange={(e) => setMode(e.target.value as CensorMode)}
          disabled={committing}
          className="bg-slate-800 border border-slate-700 px-2 py-1 text-slate-200 rounded"
        >
          {(Object.keys(MODE_LABELS) as CensorMode[]).map((m) => (
            <option key={m} value={m}>
              {MODE_LABELS[m]}
            </option>
          ))}
        </select>
        {review.mode === "beep" && (
          <>
            <label htmlFor="beep-hz" className="text-slate-400">Frequency</label>
            <input
              id="beep-hz"
              type="number"
              min={200}
              max={8000}
              step={100}
              value={review.beepHz}
              onChange={(e) => setBeepHz(Number(e.target.value))}
              className="w-20 bg-slate-800 border border-slate-700 px-1 text-slate-200 rounded"
              disabled={committing}
            />
            <span>Hz</span>
          </>
        )}
        <p className="text-xs text-slate-500 w-full italic">
          {MODE_DESCRIPTIONS[review.mode]}
        </p>
      </div>

      {hasNonExactMatches && (
        <div className="flex items-center gap-3">
          <label className="text-xs text-slate-500" htmlFor="profanity-confidence">
            Confidence floor
          </label>
          <input
            id="profanity-confidence"
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
      )}

      {total === 0 ? (
        <p className="text-sm text-slate-400">
          No profanity detected in this audio.
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
                  {r.matchedBy}
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
