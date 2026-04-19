import { useState } from "react";
import { enqueueOperation, pollOperation } from "../api/operations";
import { useEditorStore } from "../store/editorStore";
import WaveformPlayer from "../audio/WaveformPlayer";
import WaveformErrorBoundary from "../audio/WaveformErrorBoundary";
import SelectionInfo from "./SelectionInfo";
import OperationPanel from "./OperationPanel";

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
      if (res.asset) pushAsset(res.asset, false);
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
      {/* Channel tabs */}
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-slate-400">Editing Channels:</span>
        <button
          onClick={() => setActiveChannel("left")}
          className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
            activeChannel === "left"
              ? "bg-blue-600 text-white"
              : "bg-slate-700 text-slate-300 hover:bg-slate-600"
          }`}
        >
          Left Channel
        </button>
        <button
          onClick={() => setActiveChannel("right")}
          className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
            activeChannel === "right"
              ? "bg-blue-600 text-white"
              : "bg-slate-700 text-slate-300 hover:bg-slate-600"
          }`}
        >
          Right Channel
        </button>
        <div className="flex-1" />
        <button
          onClick={handleMerge}
          disabled={isProcessing || isMerging}
          className="px-4 py-1.5 bg-green-600 hover:bg-green-700 disabled:opacity-40 disabled:cursor-not-allowed rounded text-sm text-white font-medium transition-colors"
        >
          {isMerging ? "Merging..." : "Merge to Stereo"}
        </button>
        <button
          onClick={exitChannelEdit}
          disabled={isProcessing}
          className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 rounded text-sm text-slate-300 transition-colors"
        >
          Cancel
        </button>
      </div>

      {/* Channel info */}
      <div className="flex gap-4 text-xs text-slate-500">
        <span className={activeChannel === "left" ? "text-blue-400" : ""}>
          L: {leftAsset.durationSec?.toFixed(1)}s / {leftAsset.sampleRate}Hz
        </span>
        <span className={activeChannel === "right" ? "text-blue-400" : ""}>
          R: {rightAsset.durationSec?.toFixed(1)}s / {rightAsset.sampleRate}Hz
        </span>
      </div>

      {/* Waveform for active channel */}
      <WaveformErrorBoundary onReset={() => setError(null)}>
        <WaveformPlayer />
      </WaveformErrorBoundary>
      <SelectionInfo />

      {/* Operations apply to active channel */}
      <OperationPanel />
    </div>
  );
}
