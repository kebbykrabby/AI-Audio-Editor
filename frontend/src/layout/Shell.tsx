import AuthGate from "../auth/AuthGate";
import UserMenu from "../auth/UserMenu";
import { useEditorStore } from "../store/editorStore";
import { useRestoreSession } from "../store/useRestoreSession";
import UploadZone from "./UploadZone";
import Toolbar from "./Toolbar";
import WaveformPlayer from "../audio/WaveformPlayer";
import WaveformErrorBoundary from "../audio/WaveformErrorBoundary";
import SelectionInfo from "../editor/SelectionInfo";
import OperationPanel from "../editor/OperationPanel";
import ChannelEditor from "../editor/ChannelEditor";
import FillerReviewPanel from "../editor/FillerReviewPanel";
import ProfanityReviewPanel from "../editor/ProfanityReviewPanel";

function Workspace() {
  const { isRestoring } = useRestoreSession();
  const asset = useEditorStore((s) => s.currentAsset());
  const error = useEditorStore((s) => s.error);
  const warning = useEditorStore((s) => s.warning);
  const isProcessing = useEditorStore((s) => s.isProcessing);
  const setError = useEditorStore((s) => s.setError);
  const setWarning = useEditorStore((s) => s.setWarning);
  const channelEdit = useEditorStore((s) => s.channelEdit);
  const activeFillerReview = useEditorStore((s) => s.activeFillerReview);
  const activeProfanityReview = useEditorStore((s) => s.activeProfanityReview);

  if (isRestoring) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-slate-400 text-sm">Restoring session…</div>
      </div>
    );
  }

  if (!asset || asset.status !== "ready") {
    return (
      <div className="min-h-screen flex flex-col">
        <header className="flex items-center justify-between px-4 py-2 border-b border-slate-800">
          <div className="text-slate-200 font-medium">AI Audio Editor</div>
          <UserMenu />
        </header>
        <UploadZone />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="flex items-center justify-between px-4 py-2 border-b border-slate-800">
        <Toolbar />
        <UserMenu />
      </header>

      {error && (
        <div className="px-4 py-2 bg-red-900/50 border-b border-red-800 text-red-300 text-sm flex justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200">
            dismiss
          </button>
        </div>
      )}
      {warning && (
        <div className="px-4 py-2 bg-yellow-900/50 border-b border-yellow-800 text-yellow-300 text-sm flex justify-between">
          <span>{warning}</span>
          <button onClick={() => setWarning(null)} className="text-yellow-400 hover:text-yellow-200">
            dismiss
          </button>
        </div>
      )}
      {isProcessing && (
        <div className="px-4 py-2 bg-blue-900/50 border-b border-blue-800 text-blue-300 text-sm">
          Processing operation…
        </div>
      )}

      <div className="flex-1 p-4 space-y-4">
        {channelEdit ? (
          <ChannelEditor />
        ) : (
          <>
            <WaveformErrorBoundary onReset={() => setError(null)}>
              <WaveformPlayer />
            </WaveformErrorBoundary>
            <SelectionInfo />
            {activeFillerReview ? (
              <FillerReviewPanel />
            ) : activeProfanityReview ? (
              <ProfanityReviewPanel />
            ) : (
              <OperationPanel />
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function Shell() {
  return (
    <AuthGate>
      <Workspace />
    </AuthGate>
  );
}
