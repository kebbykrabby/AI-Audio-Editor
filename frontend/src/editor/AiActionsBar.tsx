import { useState } from "react";
import { MessageSquare, Settings, ShieldAlert, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { detectFillers, detectProfanity } from "../api/ai";
import { ApiRequestError } from "../api/client";
import { generateNlePlan } from "../api/nle";
import { useEditorStore } from "../store/editorStore";
import CensorshipSettingsModal from "./CensorshipSettingsModal";

/**
 * AI-actions surface: two review-flow triggers (fillers, profanity) plus the
 * "Ask AI" NLE prompt. Every action calls the backend AI endpoint, then hands
 * the returned operationId + result to `enter{X}Review`, which is what makes
 * the panel switch in Shell.tsx swap to the review UI.
 *
 * No audio changes here — this is the "propose" half of review-before-apply.
 */
export default function AiActionsBar() {
  const asset = useEditorStore((s) => s.currentAsset());
  const selection = useEditorStore((s) => s.selection);
  const isProcessing = useEditorStore((s) => s.isProcessing);
  const setError = useEditorStore((s) => s.setError);
  const setWarning = useEditorStore((s) => s.setWarning);
  const enterFillerReview = useEditorStore((s) => s.enterFillerReview);
  const enterProfanityReview = useEditorStore((s) => s.enterProfanityReview);
  const enterNlePlanReview = useEditorStore((s) => s.enterNlePlanReview);

  const [detectingFillers, setDetectingFillers] = useState(false);
  const [detectingProfanity, setDetectingProfanity] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [nlePrompt, setNlePrompt] = useState("");
  const [censorSettingsOpen, setCensorSettingsOpen] = useState(false);

  if (!asset) return null;

  const friendlyMessage = (e: unknown): string => {
    if (e instanceof ApiRequestError) return e.message;
    return e instanceof Error ? e.message : "Operation failed";
  };

  const handleFindFillers = async () => {
    if (detectingFillers || isProcessing) return;
    const durationSec = asset.durationSec ?? 0;
    const confirmMsg =
      `Find filler words in this audio?\n\n` +
      `Duration: ${durationSec.toFixed(1)}s\n` +
      `The audio will be transcribed by the configured AI provider.`;
    if (!window.confirm(confirmMsg)) return;

    setError(null);
    setDetectingFillers(true);
    try {
      const { operationId, result } = await detectFillers(asset.assetId, {
        confidence_threshold: 0,
      });
      enterFillerReview({
        operationId,
        inputAssetId: asset.assetId,
        result,
        rejectedWordIndices: new Set(),
        confidenceThreshold: 0.7,
      });
      if (result.regions.length === 0) {
        setWarning("No filler words detected in this audio.");
      }
    } catch (e) {
      setError(friendlyMessage(e));
    } finally {
      setDetectingFillers(false);
    }
  };

  const handleCensorProfanity = async () => {
    if (detectingProfanity || isProcessing) return;
    const durationSec = asset.durationSec ?? 0;
    const confirmMsg =
      `Find profanity in this audio?\n\n` +
      `Duration: ${durationSec.toFixed(1)}s\n` +
      `The audio will be transcribed by the configured AI provider; detected ` +
      `words will be replaced with a beep when you apply.`;
    if (!window.confirm(confirmMsg)) return;

    setError(null);
    setDetectingProfanity(true);
    try {
      const { operationId, result } = await detectProfanity(asset.assetId);
      enterProfanityReview({
        operationId,
        inputAssetId: asset.assetId,
        result,
        rejectedWordIndices: new Set(),
        confidenceThreshold: 0,
        mode: "beep",
        beepHz: 1000,
      });
      if (result.regions.length === 0) {
        setWarning("No profanity detected in this audio.");
      }
    } catch (e) {
      setError(friendlyMessage(e));
    } finally {
      setDetectingProfanity(false);
    }
  };

  const handleAskAi = async () => {
    if (planning || isProcessing) return;
    const trimmed = nlePrompt.trim();
    if (!trimmed) {
      setError("Type a description of what you want the AI to do.");
      return;
    }
    setError(null);
    setPlanning(true);
    try {
      const { operationId, result } = await generateNlePlan(asset.assetId, {
        prompt: trimmed,
        selection: selection
          ? { startSec: selection.startSec, endSec: selection.endSec }
          : null,
      });
      enterNlePlanReview({
        operationId,
        inputAssetId: asset.assetId,
        result,
        excludedStepIndices: new Set(),
        applyProgress: null,
      });
    } catch (e) {
      setError(friendlyMessage(e));
    } finally {
      setPlanning(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          className="gap-1.5"
          disabled={isProcessing || detectingFillers}
          onClick={handleFindFillers}
          title="Detect ums, uhs, and other filler words — review before removing"
        >
          <Sparkles className="w-3.5 h-3.5" />
          {detectingFillers ? "Transcribing…" : "Find filler words"}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          className="gap-1.5"
          disabled={isProcessing || detectingProfanity}
          onClick={handleCensorProfanity}
          title="Detect profanity — review before censoring"
        >
          <ShieldAlert className="w-3.5 h-3.5" />
          {detectingProfanity ? "Transcribing…" : "Censor profanity"}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => setCensorSettingsOpen(true)}
          title="Edit censorship word list"
          aria-label="Edit censorship word list"
        >
          <Settings className="w-3.5 h-3.5" />
        </Button>
      </div>

      <div className="rounded-lg border border-border bg-card p-3 space-y-2">
        <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <MessageSquare className="w-3.5 h-3.5" />
          Ask AI
        </div>
        <p className="text-xs text-muted-foreground">
          Describe what you want in plain English. The AI proposes a plan you review
          before any audio changes.
          {selection && (
            <span className="block mt-1 text-primary">
              Your selection ({selection.startSec.toFixed(2)}s–
              {selection.endSec.toFixed(2)}s) will be passed along as context.
            </span>
          )}
        </p>
        <Textarea
          value={nlePrompt}
          onChange={(e) => setNlePrompt(e.target.value)}
          disabled={planning || isProcessing}
          rows={2}
          placeholder='e.g. "Trim the first 30 seconds and fade out over 2 seconds"'
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              void handleAskAi();
            }
          }}
        />
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground italic">
            Your audio's spoken content is transcribed and sent to the configured
            LLM provider. Free-tier providers may use submitted data for training.
          </p>
          <Button
            size="sm"
            className="shrink-0"
            onClick={handleAskAi}
            disabled={planning || isProcessing || !nlePrompt.trim()}
            title="Generate a plan (Ctrl/Cmd+Enter)"
          >
            {planning ? "Planning…" : "Plan"}
          </Button>
        </div>
      </div>

      <CensorshipSettingsModal
        open={censorSettingsOpen}
        onClose={() => setCensorSettingsOpen(false)}
      />
    </div>
  );
}
