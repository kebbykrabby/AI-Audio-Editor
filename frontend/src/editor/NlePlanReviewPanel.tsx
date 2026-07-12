import { useMemo, useRef, useState } from "react";
import { AlertTriangle, MessageSquare, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { ApiRequestError } from "../api/client";
import { generateNlePlan } from "../api/nle";
import { enqueueOperation, pollOperation } from "../api/operations";
import { useEditorStore } from "../store/editorStore";
import type { NlePlanStep } from "../store/types";

/**
 * Review panel for an LLM-generated plan of operations.
 *
 * Two modes, driven by whether the LLM returned any steps:
 *
 * - **Plan mode** — one or more tool calls came back. Each step is listed
 *   with an include/exclude checkbox, description, validation badge, and (if
 *   the step has a time range) a preview button. Invalid steps cannot be
 *   applied. Apply dispatches enabled valid steps sequentially, each one
 *   consuming the asset produced by the previous step.
 * - **Ambiguity mode** — zero tool calls + a clarifying message in
 *   `finalResponse`. We show the message and offer a refine textarea. Each
 *   refine call is independent — no chat history is sent (D4 in the design
 *   doc).
 */

const DURATION_CHANGING_OPS = new Set(["trim", "delete", "remove_silence", "speed"]);

function previewRange(step: NlePlanStep): [number, number] | null {
  const p = step.operation.parameters as Record<string, unknown>;
  const t = step.operation.type;
  const num = (k: string) => (typeof p[k] === "number" ? (p[k] as number) : null);

  if (t === "trim" || t === "delete" || t === "reverse_range" || t === "gain_range") {
    const s = num("start_sec");
    const e = num("end_sec");
    return s !== null && e !== null && e > s ? [s, e] : null;
  }
  if (t === "fade_in") {
    const d = num("duration_sec");
    return d !== null && d > 0 ? [0, d] : null;
  }
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

  const enabledSteps = useMemo<NlePlanStep[]>(() => {
    if (!review) return [];
    return review.result.steps.filter(
      (s) =>
        s.validationStatus === "valid" && !review.excludedStepIndices.has(s.stepIndex),
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
          // Truncate LLM descriptions so the history rows stay one line.
          const shortLabel =
            step.description.length > 40
              ? step.description.slice(0, 37) + "…"
              : step.description || `AI step: ${step.operation.type}`;
          pushAsset(completed.asset, durationChanged, `AI · ${shortLabel}`);
          currentAssetId = completed.asset.assetId;
        }
      }
      exitReview();
    } catch (e) {
      if (e instanceof ApiRequestError && e.code === "ABORTED") return;
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
      abortRef.current?.abort();
      return;
    }
    exitReview();
  };

  const handleRefine = async () => {
    if (!asset || refining) return;
    const trimmed = refinePrompt.trim();
    if (!trimmed) return;
    setRefining(true);
    setError(null);
    try {
      const { operationId, result: newResult } = await generateNlePlan(asset.assetId, {
        prompt: trimmed,
        selection: selection
          ? { startSec: selection.startSec, endSec: selection.endSec }
          : null,
      });
      enterReview({
        operationId,
        inputAssetId: asset.assetId,
        result: newResult,
        excludedStepIndices: new Set(),
        applyProgress: null,
      });
      setRefinePrompt("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Re-plan failed; try again or cancel.");
    } finally {
      setRefining(false);
    }
  };

  // --- Ambiguity mode -------------------------------------------------------
  if (isAmbiguity) {
    return (
      <div className="rounded-lg border border-border bg-card p-4 space-y-4 shadow-sm">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-foreground flex items-center gap-1.5">
              <MessageSquare className="w-3.5 h-3.5 text-primary" />
              Plan needs clarification
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5 truncate">
              You asked: <span className="italic">{result.prompt}</span>
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={exitReview} disabled={refining}>
            Cancel
          </Button>
        </div>

        <p className="text-sm text-foreground bg-muted rounded-md p-3 whitespace-pre-wrap">
          {result.finalResponse ||
            "The AI didn't propose any operations. Try rephrasing with more specifics."}
        </p>

        <div className="space-y-2">
          <Label htmlFor="nle-refine" className="text-xs">
            Refine your request
          </Label>
          <Textarea
            id="nle-refine"
            value={refinePrompt}
            onChange={(e) => setRefinePrompt(e.target.value)}
            disabled={refining}
            rows={2}
            placeholder="e.g. add details, pick a tool from the list, or constrain the timestamps"
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                e.preventDefault();
                void handleRefine();
              }
            }}
          />
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground italic">
              Each Re-plan is independent — the AI doesn't see your previous turns.
            </p>
            <Button
              size="sm"
              onClick={handleRefine}
              disabled={refining || !refinePrompt.trim()}
              title="Send a refined prompt (Ctrl/Cmd+Enter)"
            >
              {refining ? "Re-planning…" : "Re-plan"}
            </Button>
          </div>
        </div>

      </div>
    );
  }

  // --- Plan mode ------------------------------------------------------------
  const total = result.steps.length;
  const validCount = result.steps.filter((s) => s.validationStatus === "valid").length;
  const invalidCount = total - validCount;

  return (
    <div className="rounded-lg border border-border bg-card shadow-sm flex flex-col overflow-hidden">
      {/* Header — title alone on a row, meta below, no LLM branding. */}
      <div className="p-3 border-b border-border space-y-1.5">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-1.5">
          <MessageSquare className="w-3.5 h-3.5 text-primary" />
          Review AI plan
        </h3>
        <p className="text-xs text-muted-foreground break-words">
          You asked: <span className="italic">{result.prompt}</span>
        </p>
        <p className="text-xs text-muted-foreground">
          {enabledSteps.length} of {validCount} valid step
          {validCount === 1 ? "" : "s"} selected
          {invalidCount > 0 && (
            <span className="text-yellow-600">
              {" · "}{invalidCount} invalid
            </span>
          )}
        </p>
        {review.applyProgress && (
          <p className="text-xs text-primary">
            Applying step {review.applyProgress.currentIndex + 1} of{" "}
            {review.applyProgress.totalEnabled}…
          </p>
        )}
      </div>

      {result.finalResponse && (
        <p className="mx-3 mt-3 text-xs text-muted-foreground italic bg-muted rounded-md p-2">
          {result.finalResponse}
        </p>
      )}

      {/* Steps list — sidebar-friendly rows: description first, op-type badge
          on a second line so nothing overflows in narrow widths. */}
      <ScrollArea className="max-h-64 mx-3 my-3 rounded-md border border-border">
        <ol className="divide-y divide-border">
          {result.steps.map((step) => {
            const isInvalid = step.validationStatus === "invalid";
            const isExcluded = review.excludedStepIndices.has(step.stepIndex);
            const isEnabled = !isInvalid && !isExcluded;
            const range = previewRange(step);
            return (
              <li
                key={step.stepIndex}
                className={`px-2 py-1.5 text-sm transition-colors ${
                  isEnabled ? "bg-background" : "bg-muted/40 text-muted-foreground"
                }`}
              >
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => range && playRange(range[0], range[1])}
                    disabled={!range || applying}
                    className="flex items-center justify-center w-6 h-6 rounded hover:bg-accent text-muted-foreground hover:text-foreground disabled:opacity-30 shrink-0"
                    aria-label={`Preview step ${step.stepIndex + 1}`}
                    title={range ? "Preview the time range this step affects" : "No preview for this step"}
                  >
                    <Play className="w-3 h-3" />
                  </button>
                  <Checkbox
                    checked={isEnabled}
                    disabled={isInvalid || applying}
                    onCheckedChange={() => toggleStep(step.stepIndex)}
                    aria-label={`Toggle step ${step.stepIndex + 1}`}
                  />
                  <span className="font-mono text-xs text-muted-foreground tabular-nums shrink-0">
                    {step.stepIndex + 1}.
                  </span>
                  <span className="flex-1 min-w-0 break-words text-xs leading-snug">
                    {step.description}
                  </span>
                </div>
                <div className="flex items-center gap-1 mt-1 pl-8">
                  <span
                    className={`text-[10px] uppercase tracking-wide ${
                      isInvalid ? "text-yellow-600" : "text-muted-foreground"
                    }`}
                    title={step.validationError ?? "valid"}
                  >
                    {step.operation.type}
                  </span>
                  {isInvalid && (
                    <span
                      className="text-[10px] text-yellow-600 flex items-center gap-1 min-w-0"
                      title={step.validationError ?? ""}
                    >
                      <AlertTriangle className="w-3 h-3 shrink-0" />
                      <span className="truncate">{step.validationError ?? "invalid"}</span>
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </ScrollArea>

      {/* Apply / Cancel — sticky footer, full-width buttons so they always fit. */}
      <div className="px-3 pb-3 flex gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={handleCancel}
          className="flex-1"
          title={applying ? "Stop applying further steps" : "Discard plan"}
        >
          Cancel
        </Button>
        <Button
          size="sm"
          onClick={handleApply}
          disabled={applying || isProcessing || enabledSteps.length === 0}
          className="flex-1"
          title="Apply the selected steps in order"
        >
          {applying
            ? "Applying…"
            : `Apply ${enabledSteps.length}`}
        </Button>
      </div>

      {/* Chat-style refinement — send a follow-up prompt to swap the current
          plan for a new one. Each refine is independent (no chat history is
          sent server-side); the user re-states their full intent. */}
      <div className="border-t border-border px-3 py-3 space-y-2 bg-muted/30">
        <Label htmlFor="nle-plan-refine" className="text-xs flex items-center gap-1.5">
          <MessageSquare className="w-3 h-3" />
          Ask for changes
        </Label>
        <Textarea
          id="nle-plan-refine"
          value={refinePrompt}
          onChange={(e) => setRefinePrompt(e.target.value)}
          disabled={refining || applying}
          rows={2}
          placeholder='e.g. "Make the fade 3 seconds instead" or "Add a normalize step"'
          className="text-xs"
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              void handleRefine();
            }
          }}
        />
        <Button
          size="sm"
          onClick={handleRefine}
          disabled={refining || applying || !refinePrompt.trim()}
          className="w-full gap-1.5"
          title="Send a new prompt to replace this plan (Ctrl/Cmd+Enter)"
        >
          <MessageSquare className="w-3 h-3" />
          {refining ? "Rethinking…" : "Send"}
        </Button>
      </div>
    </div>
  );
}
