import { useEffect } from "react";
import { Navigate } from "react-router-dom";
import { Music } from "lucide-react";

import UserMenu from "../auth/UserMenu";
import { useEditorStore } from "../store/editorStore";
import { useRestoreSession } from "../store/useRestoreSession";
import Toolbar from "./Toolbar";
import TransportBar from "./TransportBar";
import WaveformPlayer from "../audio/WaveformPlayer";
import WaveformErrorBoundary from "../audio/WaveformErrorBoundary";
import EditToolbar from "../editor/EditToolbar";
import OperationPanel from "../editor/OperationPanel";
import ChannelEditor from "../editor/ChannelEditor";
import FillerReviewPanel from "../editor/FillerReviewPanel";
import NlePlanReviewPanel from "../editor/NlePlanReviewPanel";
import ProfanityReviewPanel from "../editor/ProfanityReviewPanel";
import VersionHistoryPanel from "../editor/VersionHistoryPanel";

/**
 * Editor screen (route: `/editor`). AuthGate is applied one level up in App;
 * if the user has no ready asset (fresh session, no persisted tip, or a
 * failed restore), we send them back to the Dashboard where they can upload
 * or pick a project.
 */
export default function Shell() {
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
  const activeNlePlanReview = useEditorStore((s) => s.activeNlePlanReview);

  // Wipe any lingering error/warning banners on unmount so navigating away and
  // back doesn't re-show stale messages.
  useEffect(() => {
    return () => {
      setError(null);
      setWarning(null);
    };
  }, [setError, setWarning]);

  if (isRestoring) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background">
        <div className="text-muted-foreground text-sm">Restoring session…</div>
      </div>
    );
  }

  if (!asset || asset.status !== "ready") {
    // No asset in this session and no persisted tip to restore — go pick one.
    return <Navigate to="/" replace />;
  }

  return (
    <div className="min-h-screen flex flex-col bg-background">
      <header className="h-12 border-b border-border bg-card flex items-center px-4 gap-3 shrink-0">
        <div className="w-7 h-7 rounded-md bg-primary flex items-center justify-center shrink-0">
          <Music className="w-3.5 h-3.5 text-primary-foreground" />
        </div>
        <div className="flex-1 min-w-0">
          <Toolbar />
        </div>
        <UserMenu />
      </header>

      {!channelEdit && <EditToolbar />}

      {isProcessing && (
        <div className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm flex items-center justify-center pointer-events-none">
          <div className="rounded-lg border border-border bg-card px-4 py-3 shadow-lg text-sm text-foreground pointer-events-auto">
            Processing…
          </div>
        </div>
      )}

      {error && (
        <div
          className="px-4 py-2 border-b border-destructive/30 bg-destructive/10 text-destructive text-sm flex justify-between items-center"
          role="alert"
        >
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
            className="text-destructive/70 hover:text-destructive text-xs uppercase tracking-wide"
          >
            dismiss
          </button>
        </div>
      )}
      {warning && (
        <div className="px-4 py-2 border-b bg-yellow-100 text-yellow-900 border-yellow-300 text-sm flex justify-between items-center">
          <span>{warning}</span>
          <button
            onClick={() => setWarning(null)}
            className="text-yellow-700 hover:text-yellow-900 text-xs uppercase tracking-wide"
          >
            dismiss
          </button>
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
            <TransportBar />
            {activeFillerReview ? (
              <FillerReviewPanel />
            ) : activeProfanityReview ? (
              <ProfanityReviewPanel />
            ) : activeNlePlanReview ? (
              <NlePlanReviewPanel />
            ) : (
              <OperationPanel />
            )}
            <VersionHistoryPanel />
          </>
        )}
      </div>
    </div>
  );
}
