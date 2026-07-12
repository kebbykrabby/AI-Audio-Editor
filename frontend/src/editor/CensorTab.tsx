import { useState } from "react";
import { Settings, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { detectProfanity } from "../api/ai";
import { ApiRequestError } from "../api/client";
import { useEditorStore } from "../store/editorStore";
import CensorshipSettingsModal from "./CensorshipSettingsModal";
import ProfanityReviewPanel from "./ProfanityReviewPanel";

/**
 * Censor tab: profanity detection trigger + review, plus a gear button that
 * opens the word-list / matcher settings modal.
 */
export default function CensorTab() {
  const activeReview = useEditorStore((s) => s.activeProfanityReview);
  const asset = useEditorStore((s) => s.currentAsset());
  const isProcessing = useEditorStore((s) => s.isProcessing);
  const setError = useEditorStore((s) => s.setError);
  const setWarning = useEditorStore((s) => s.setWarning);
  const enterReview = useEditorStore((s) => s.enterProfanityReview);

  const [detecting, setDetecting] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  if (activeReview) {
    return (
      <div className="p-3 overflow-y-auto h-full">
        <ProfanityReviewPanel />
      </div>
    );
  }

  const handleDetect = async () => {
    if (!asset || detecting || isProcessing) return;
    const durationSec = asset.durationSec ?? 0;
    const confirmMsg =
      `Find profanity in this audio?\n\n` +
      `Duration: ${durationSec.toFixed(1)}s\n` +
      `The audio will be transcribed by the configured AI provider; detected ` +
      `words will be replaced with a beep when you apply.`;
    if (!window.confirm(confirmMsg)) return;

    setError(null);
    setDetecting(true);
    try {
      const { operationId, result } = await detectProfanity(asset.assetId);
      enterReview({
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
      const msg = e instanceof ApiRequestError ? e.message : "Detection failed";
      setError(msg);
    } finally {
      setDetecting(false);
    }
  };

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-primary" />
          <h3 className="text-sm font-semibold">Censor profanity</h3>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => setSettingsOpen(true)}
          title="Edit censorship word list"
          aria-label="Edit censorship word list"
        >
          <Settings className="w-3.5 h-3.5" />
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Matches user + built-in word lists (exact, stem-variants, phonetic).
        Review each detection before applying. Four modes: beep, mute, cut, or
        reverse-and-pitch-shift.
      </p>
      <Button
        onClick={handleDetect}
        disabled={detecting || isProcessing || !asset}
        className="w-full gap-1.5"
      >
        <ShieldAlert className="w-3.5 h-3.5" />
        {detecting ? "Transcribing…" : "Find profanity"}
      </Button>

      <CensorshipSettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  );
}
