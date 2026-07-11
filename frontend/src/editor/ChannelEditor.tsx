import { useState } from "react";
import { Merge } from "lucide-react";

import { Button } from "@/components/ui/button";
import WaveformErrorBoundary from "../audio/WaveformErrorBoundary";
import WaveformPlayer from "../audio/WaveformPlayer";
import TransportBar from "../layout/TransportBar";
import { enqueueOperation, pollOperation } from "../api/operations";
import { useEditorStore } from "../store/editorStore";
import EditToolbar from "./EditToolbar";
import OperationPanel from "./OperationPanel";

/**
 * Sub-mode: the user split a stereo asset into (L, R) and is editing each
 * side independently. Rendered instead of the normal editor body when
 * `channelEdit` is set.
 *
 * We re-mount `WaveformPlayer + TransportBar + EditToolbar + OperationPanel`
 * inside this container. `currentAsset()` in the store returns the active
 * channel while `channelEdit` is set, so those inner components stay
 * unaware they're in channel-edit mode.
 */
export default function ChannelEditor() {
  const channelEdit = useEditorStore((s) => s.channelEdit);
  const setActiveChannel = useEditorStore((s) => s.setActiveChannel);
  const exitChannelEdit = useEditorStore((s) => s.exitChannelEdit);
  const pushAsset = useEditorStore((s) => s.pushAsset);
  const setProcessing = useEditorStore((s) => s.setProcessing);
  const setError = useEditorStore((s) => s.setError);
  const isProcessing = useEditorStore((s) => s.isProcessing);
  const [isMerging, setIsMerging] = useState(false);

  if (!channelEdit) return null;

  const { leftAsset, rightAsset, activeChannel } = channelEdit;

  const handleMerge = async () => {
    setIsMerging(true);
    setProcessing(true);
    setError(null);
    try {
      const queued = await enqueueOperation("merge_channels", leftAsset.assetId, {
        right_asset_id: rightAsset.assetId,
      });
      const res = await pollOperation(queued.operationId);
      if (res.asset) pushAsset(res.asset, false, "Merged channels to stereo");
      exitChannelEdit();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Merge failed");
    } finally {
      setIsMerging(false);
      setProcessing(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Channel selector + merge controls */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-muted-foreground">Editing channel:</span>
        <Button
          size="sm"
          variant={activeChannel === "left" ? "default" : "secondary"}
          onClick={() => setActiveChannel("left")}
        >
          Left
        </Button>
        <Button
          size="sm"
          variant={activeChannel === "right" ? "default" : "secondary"}
          onClick={() => setActiveChannel("right")}
        >
          Right
        </Button>
        <div className="flex-1" />
        <Button
          size="sm"
          className="gap-1.5"
          onClick={handleMerge}
          disabled={isProcessing || isMerging}
        >
          <Merge className="w-3.5 h-3.5" />
          {isMerging ? "Merging…" : "Merge to Stereo"}
        </Button>
        <Button size="sm" variant="ghost" onClick={exitChannelEdit} disabled={isProcessing}>
          Cancel
        </Button>
      </div>

      {/* Channel meta */}
      <div className="flex gap-4 text-xs text-muted-foreground font-mono">
        <span className={activeChannel === "left" ? "text-primary" : ""}>
          L: {leftAsset.durationSec?.toFixed(1)}s · {leftAsset.sampleRate} Hz
        </span>
        <span className={activeChannel === "right" ? "text-primary" : ""}>
          R: {rightAsset.durationSec?.toFixed(1)}s · {rightAsset.sampleRate} Hz
        </span>
      </div>

      {/* EditToolbar scoped to the active channel */}
      <EditToolbar />

      <WaveformErrorBoundary onReset={() => setError(null)}>
        <WaveformPlayer />
      </WaveformErrorBoundary>
      <TransportBar />

      <OperationPanel />
    </div>
  );
}
