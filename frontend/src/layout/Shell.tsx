import { useEditorStore } from "../store/editorStore";
import UploadZone from "./UploadZone";
import Toolbar from "./Toolbar";
import WaveformPlayer from "../audio/WaveformPlayer";
import WaveformErrorBoundary from "../audio/WaveformErrorBoundary";
import SelectionInfo from "../editor/SelectionInfo";
import OperationPanel from "../editor/OperationPanel";

export default function Shell() {
  const asset = useEditorStore((s) => s.currentAsset());
  const error = useEditorStore((s) => s.error);
  const warning = useEditorStore((s) => s.warning);
  const isProcessing = useEditorStore((s) => s.isProcessing);
  const setError = useEditorStore((s) => s.setError);
  const setWarning = useEditorStore((s) => s.setWarning);

  if (!asset || asset.status !== "ready") {
    return <UploadZone />;
  }

  return (
    <div className="min-h-screen flex flex-col">
      <Toolbar />

      {/* Notifications */}
      {error && (
        <div className="px-4 py-2 bg-red-900/50 border-b border-red-800 text-red-300 text-sm flex justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200">dismiss</button>
        </div>
      )}
      {warning && (
        <div className="px-4 py-2 bg-yellow-900/50 border-b border-yellow-800 text-yellow-300 text-sm flex justify-between">
          <span>{warning}</span>
          <button onClick={() => setWarning(null)} className="text-yellow-400 hover:text-yellow-200">dismiss</button>
        </div>
      )}

      {/* Processing overlay */}
      {isProcessing && (
        <div className="px-4 py-2 bg-blue-900/50 border-b border-blue-800 text-blue-300 text-sm">
          Processing operation...
        </div>
      )}

      {/* Editor area */}
      <div className="flex-1 p-4 space-y-4">
        <WaveformErrorBoundary onReset={() => setError(null)}>
          <WaveformPlayer />
        </WaveformErrorBoundary>
        <SelectionInfo />
        <OperationPanel />
      </div>
    </div>
  );
}
