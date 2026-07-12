import { useState } from "react";
import { Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { detectFillers } from "../api/ai";
import { ApiRequestError } from "../api/client";
import { useEditorStore } from "../store/editorStore";
import FillerReviewPanel from "./FillerReviewPanel";

/**
 * Fillers tab: either the review UI (when a filler review is active) or the
 * trigger button (idle state).
 */
export default function FillersTab() {
  const activeReview = useEditorStore((s) => s.activeFillerReview);
  const asset = useEditorStore((s) => s.currentAsset());
  const isProcessing = useEditorStore((s) => s.isProcessing);
  const setError = useEditorStore((s) => s.setError);
  const setWarning = useEditorStore((s) => s.setWarning);
  const enterReview = useEditorStore((s) => s.enterFillerReview);

  const [detecting, setDetecting] = useState(false);

  // When a review is active, render the review UI — takes the full tab area.
  if (activeReview) {
    return (
      <div className="h-full p-3">
        <FillerReviewPanel />
      </div>
    );
  }

  const handleDetect = async () => {
    if (!asset || detecting || isProcessing) return;
    const durationSec = asset.durationSec ?? 0;
    const confirmMsg =
      `Find filler words in this audio?\n\n` +
      `Duration: ${durationSec.toFixed(1)}s\n` +
      `The audio will be transcribed by the configured AI provider.`;
    if (!window.confirm(confirmMsg)) return;

    setError(null);
    setDetecting(true);
    try {
      const { operationId, result } = await detectFillers(asset.assetId, {
        confidence_threshold: 0,
      });
      enterReview({
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
      const msg = e instanceof ApiRequestError ? e.message : "Detection failed";
      setError(msg);
    } finally {
      setDetecting(false);
    }
  };

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-primary" />
        <h3 className="text-sm font-semibold">Filler words</h3>
      </div>
      <p className="text-xs text-muted-foreground">
        Transcribes the audio and flags every "um", "uh", and stutter with a
        confidence score. Review the list before any audio changes; approve to
        remove them with a short crossfade.
      </p>
      <Button
        onClick={handleDetect}
        disabled={detecting || isProcessing || !asset}
        className="w-full gap-1.5"
      >
        <Sparkles className="w-3.5 h-3.5" />
        {detecting ? "Transcribing…" : "Find filler words"}
      </Button>
    </div>
  );
}
