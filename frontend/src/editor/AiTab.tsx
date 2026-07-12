import { useState } from "react";
import { MessageSquare } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiRequestError } from "../api/client";
import { generateNlePlan } from "../api/nle";
import { useEditorStore } from "../store/editorStore";
import NlePlanReviewPanel from "./NlePlanReviewPanel";

/**
 * AI tab: natural-language editor. Textarea for the user's prompt, "Propose
 * Edits" button that calls the LLM; when a plan comes back, this tab hosts
 * the review UI.
 */
export default function AiTab() {
  const activeReview = useEditorStore((s) => s.activeNlePlanReview);
  const asset = useEditorStore((s) => s.currentAsset());
  const selection = useEditorStore((s) => s.selection);
  const isProcessing = useEditorStore((s) => s.isProcessing);
  const setError = useEditorStore((s) => s.setError);
  const enterReview = useEditorStore((s) => s.enterNlePlanReview);

  const [prompt, setPrompt] = useState("");
  const [planning, setPlanning] = useState(false);

  if (activeReview) {
    return (
      <div className="h-full p-3">
        <NlePlanReviewPanel />
      </div>
    );
  }

  const handleAskAi = async () => {
    if (!asset || planning || isProcessing) return;
    const trimmed = prompt.trim();
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
      enterReview({
        operationId,
        inputAssetId: asset.assetId,
        result,
        excludedStepIndices: new Set(),
        applyProgress: null,
      });
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Plan failed");
    } finally {
      setPlanning(false);
    }
  };

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-2">
        <MessageSquare className="w-4 h-4 text-primary" />
        <h3 className="text-sm font-semibold">AI Editor</h3>
      </div>
      <p className="text-xs text-muted-foreground">
        Describe what you want to do in plain English
      </p>
      <Textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        disabled={planning || isProcessing}
        rows={4}
        placeholder={`e.g. "Fade in the first 3 seconds and normalize the whole clip" or "Speed up the middle section slightly"`}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            void handleAskAi();
          }
        }}
        className="text-xs"
      />
      {selection && (
        <p className="text-[11px] text-primary">
          Your selection ({selection.startSec.toFixed(2)}s–
          {selection.endSec.toFixed(2)}s) will be passed as context.
        </p>
      )}
      <Button
        onClick={handleAskAi}
        disabled={planning || isProcessing || !prompt.trim() || !asset}
        className="w-full gap-1.5"
        title="Generate a plan (Ctrl/Cmd+Enter)"
      >
        <MessageSquare className="w-3.5 h-3.5" />
        {planning ? "Planning…" : "Propose Edits"}
      </Button>
      <p className="text-[11px] text-muted-foreground italic">
        Your audio's spoken content is transcribed and sent to the configured
        LLM provider. Free-tier providers may use submitted data for training.
      </p>
    </div>
  );
}
