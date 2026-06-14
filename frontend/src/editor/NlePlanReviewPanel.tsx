import { useMemo, useRef, useState } from "react";
import { ApiRequestError } from "../api/client";
import { generateNlePlan } from "../api/nle";
import { enqueueOperation, pollOperation } from "../api/operations";
import { useEditorStore } from "../store/editorStore";
import type { NlePlanStep } from "../store/types";

/**
 * Review panel for an LLM-generated plan of operations.
 *
 * Two modes:
 * - **Plan mode** — the LLM returned one or more tool calls. Each step is
 *   listed with a checkbox (include/exclude), description, and validation
 *   badge. Invalid steps cannot be applied. Apply dispatches enabled valid
 *   steps sequentially, each one consuming the asset produced by the
 *   previous step.
 * - **Ambiguity mode** — the LLM returned zero tool calls + a clarifying
 *   message in `finalResponse`. We show the message and offer Cancel only.
 *   The user re-prompts via the OperationPanel input on the next round.
 */

// Operation types that change the audio duration. Used to drive history's
// `durationChanged` flag — selection is cleared on those, preserved on others.
const DURATION_CHANGING_OPS = new Set([
  "trim", "delete", "remove_silence", "speed",
]);

// Operation types where a timestamp range is meaningful to preview. Maps a
// step's params → (start, end) tuple, or null if no preview makes sense
// (e.g. reverse, normalize — they touch the whole asset).
function previewRange(step: NlePlanStep): [number, number] | null {
  const p = step.operation.parameters as Record<string, unknown>;
  const t = step.operation.type;
  const num = (k: string) =>
    typeof p[k] === "number" ? (p[k] as number) : null;

  if (t === "trim" || t === "delete") {
    const s = num("start_sec");
    const e = num("end_sec");
    return s !== null && e !== null && e > s ? [s, e] : null;
  }
  if (t === "fade_in") {
    const d = num("duration_sec");
    return d !== null && d > 0 ? [0, d] : null;
  }
  // fade_out previews need the asset's duration to anchor against; we let the
  // caller (which has the asset on hand) build that one separately.
  return null;
}

export default function NlePlanReviewPanel() {
  const asset = useEditorStore((s) => s.currentAsset());
  const review = useEditorStore((s) => s.activeNlePlanReview);
  const toggleStep = useEditorStore((s) => s.toggleNlePlanStep);
  const setProgress = useEditorStore((s) => s.setNlePlanApplyProgress);
  const exitReview = useEditorStore((s) => s.exitNlePlanReview);
  const enterReview = useEditorStore((s) => s.enterNlePlanReview);
  const pushAsset = useEditorStore((s) => s.pushAsset);
  const setPendingOperation = useEditorStore((s) => s.setPendingOperation);
  const setError = useEditorStore((s) => s.setError);
  const isProcessing = useEditorStore((s) => s.isProcessing);
  const playRange = useEditorStore((s) => s.playRange);
  const selection = useEditorStore((s) => s.selection);

  const [applying, setApplying] = useState(false);
  const [refinePrompt, setRefinePrompt] = useState("");
  const [refining, setRefining] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Enabled valid steps in transcript order. Invalid steps never apply.
  const enabledSteps = useMemo<NlePlanStep[]>(() => {
    if (!review) return [];
    return review.result.steps.filter(
      (s) =>
        s.validationStatus === "valid" &&
        !review.excludedStepIndices.has(s.stepIndex),
    );
  }, [review]);

  if (!asset || !review) return null;

  const { result } = review;
  const isAmbiguity = result.steps.length === 0;

  const handleApply = async () => {
    if (enabledSteps.length === 0) {
      setError("Select at least one valid step to apply.");
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setApplying(true);
    setError(null);
    setProgress({ currentIndex: 0, totalEnabled: enabledSteps.length });

    let currentAssetId = review.inputAssetId;

    try {
      for (let i = 0; i < enabledSteps.length; i++) {
        const step = enabledSteps[i];
        setProgress({ currentIndex: i, totalEnabled: enabledSteps.length });

        const enqueued = await enqueueOperation(
          step.operation.type,
          currentAssetId,
          step.operation.parameters,
        );
        setPendingOperation({
          operationId: enqueued.operationId,
          type: step.operation.type,
          inputAssetId: currentAssetId,
          startedAt: Date.now(),
        });
        const completed = await pollOperation(enqueued.operationId, {
          signal: controller.signal,
        });
        if (completed.asset) {
          const durationChanged = DURATION_CHANGING_OPS.has(step.operation.type);
          pushAsset(completed.asset, durationChanged);
          currentAssetId = completed.asset.assetId;
        }
      }
      exitReview();
    } catch (e) {
      if (e instanceof ApiRequestError && e.code === "ABORTED") return;
      // We keep the partial progress in history. The user can undo individual
      // steps from there — we never auto-rollback (would be more surprising
      // than helpful per the design doc §8).
      setError(
        e instanceof Error
          ? `Plan apply stopped: ${e.message}`
          : "Plan apply stopped on an error",
      );
    } finally {
      setApplying(false);
      setPendingOperation(null);
      setProgress(null);
      abortRef.current = null;
    }
  };

  const handleCancel = () => {
    if (applying) {
      // Abort the in-flight poll. We do NOT undo completed steps.
      abortRef.current?.abort();
      return;
    }
    exitReview();
  };

  // Submits a refined prompt to the LLM and swaps the current ambiguity
  // panel for whatever it returns. Each call is independent (no chat
  // history is sent — D4 in the design doc); the user iterates by
  // re-prompting with more specificity.
  const handleRefine = async () => {
    if (!asset || refining) return;
    const trimmed = refinePrompt.trim();
    if (!trimmed) return;
    setRefining(true);
    setError(null);
    try {
      const { operationId, result } = await generateNlePlan(asset.assetId, {
        prompt: trimmed,
        selection: selection
          ? { startSec: selection.startSec, endSec: selection.endSec }
          : null,
      });
      enterReview({
        operationId,
        inputAssetId: asset.assetId,
        result,
        excludedStepIndices: new Set(),
        applyProgress: null,
      });
      setRefinePrompt("");
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Re-plan failed; try again or cancel.",
      );
    } finally {
      setRefining(false);
    }
  };

  // --- Ambiguity mode -------------------------------------------------------
  if (isAmbiguity) {
    return (
      <div className="border border-slate-700 rounded bg-slate-900 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-slate-200">
              Plan needs clarification
            </h3>
            <p className="text-xs text-slate-500">
              You asked: <span className="italic">{result.prompt}</span>
            </p>
          </div>
          <button onClick={exitReview} disabled={refining} className="op-btn">
            Cancel
          </button>
        </div>
        <p className="text-sm text-slate-300 bg-slate-800 border border-slate-700 rounded p-3 whitespace-pre-wrap">
          {result.finalResponse ||
            "The AI didn't propose any operations. Try rephrasing with more specifics."}
        </p>

        <div className="space-y-2">
          <label className="text-xs text-slate-500" htmlFor="nle-refine">
            Refine your request
          </label>
          <textarea
            id="nle-refine"
            value={refinePrompt}
            onChange={(e) => setRefinePrompt(e.target.value)}
            disabled={refining}
            rows={2}
            placeholder="e.g. add details, pick a tool from the list, or constrain the timestamps"
            className="w-full bg-slate-800 border border-slate-700 rounded p-2 text-sm text-slate-200 disabled:opacity-50 resize-y"
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                e.preventDefault();
                void handleRefine();
              }
            }}
          />
          <div className="flex justify-end">
            <button
              onClick={handleRefine}
              disabled={refining || !refinePrompt.trim()}
              className="op-btn"
              title="Send a refined prompt (Ctrl/Cmd+Enter)"
            >
              {refining ? "Re-planning…" : "Re-plan"}
            </button>
          </div>
          <p className="text-xs text-slate-600 italic">
            Each Re-plan is an independent request — the AI doesn't see your
            previous turns. State your full intent in this one prompt.
          </p>
        </div>

        <p className="text-xs text-slate-500">
          Model: <span className="font-mono">{result.modelVersion}</span>
          {result.costUsd != null && result.costUsd > 0 && (
            <> · cost: ${result.costUsd.toFixed(4)}</>
          )}
        </p>
      </div>
    );
  }

  // --- Plan mode ------------------------------------------------------------
  const total = result.steps.length;
  const validCount = result.steps.filter(
    (s) => s.validationStatus === "valid",
  ).length;
  const invalidCount = total - validCount;

  return (
    <div className="border border-slate-700 rounded bg-slate-900 p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-200">
            Review AI plan
          </h3>
          <p className="text-xs text-slate-500 truncate">
            You asked: <span className="italic">{result.prompt}</span>
          </p>
          <p className="text-xs text-slate-500 mt-0.5">
            {enabledSteps.length} of {validCount} valid step
            {validCount === 1 ? "" : "s"} selected
            {invalidCount > 0 && (
              <span className="text-yellow-500">
                {" · "}{invalidCount} invalid
              </span>
            )}
            {" · model: "}<span className="font-mono">{result.modelVersion}</span>
            {result.costUsd != null && result.costUsd > 0 && (
              <> · ${result.costUsd.toFixed(4)}</>
            )}
          </p>
          {review.applyProgress && (
            <p className="text-xs text-blue-400 mt-1">
              Applying step {review.applyProgress.currentIndex + 1} of{" "}
              {review.applyProgress.totalEnabled}…
            </p>
          )}
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            onClick={handleCancel}
            className="op-btn"
            title={applying ? "Stop applying further steps" : "Discard plan"}
          >
            Cancel
          </button>
          <button
            onClick={handleApply}
            disabled={applying || isProcessing || enabledSteps.length === 0}
            className="op-btn"
            title="Apply the selected steps in order"
          >
            {applying
              ? "Applying…"
              : `Apply ${enabledSteps.length} step${enabledSteps.length === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>

      {result.finalResponse && (
        <p className="text-xs text-slate-400 italic bg-slate-800 border border-slate-800 rounded p-2">
          {result.finalResponse}
        </p>
      )}

      <ol className="max-h-96 overflow-y-auto divide-y divide-slate-800 border border-slate-800 rounded">
        {result.steps.map((step) => {
          const isInvalid = step.validationStatus === "invalid";
          const isExcluded = review.excludedStepIndices.has(step.stepIndex);
          const isEnabled = !isInvalid && !isExcluded;
          const range = previewRange(step);
          return (
            <li
              key={step.stepIndex}
              className={`flex items-center gap-2 px-2 py-1.5 text-sm ${
                isEnabled ? "bg-slate-900" : "bg-slate-900/40 text-slate-500"
              }`}
            >
              <button
                type="button"
                onClick={() => range && playRange(range[0], range[1])}
                disabled={!range || applying}
                className="px-1.5 text-slate-400 hover:text-slate-100 disabled:opacity-30"
                aria-label={`Preview step ${step.stepIndex + 1}`}
                title={range ? "Preview the time range this step affects" : "No preview for this step"}
              >
                ▶
              </button>
              <input
                type="checkbox"
                checked={isEnabled}
                disabled={isInvalid || applying}
                onChange={() => toggleStep(step.stepIndex)}
                aria-label={`Toggle step ${step.stepIndex + 1}`}
              />
              <span className="font-mono text-xs text-slate-500 w-6 tabular-nums">
                {step.stepIndex + 1}.
              </span>
              <span className="flex-1 truncate">{step.description}</span>
              <span
                className={`text-xs uppercase tracking-wide w-16 ${
                  isInvalid ? "text-yellow-500" : "text-slate-500"
                }`}
                title={step.validationError ?? "valid"}
              >
                {step.operation.type}
              </span>
              {isInvalid && (
                <span
                  className="text-xs text-yellow-400 truncate w-32"
                  title={step.validationError ?? ""}
                >
                  ✕ {step.validationError ?? "invalid"}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
