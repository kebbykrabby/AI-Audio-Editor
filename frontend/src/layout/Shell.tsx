import { Music } from "lucide-react";

import AuthGate from "../auth/AuthGate";
import UserMenu from "../auth/UserMenu";
import { useEditorStore } from "../store/editorStore";
import { useRestoreSession } from "../store/useRestoreSession";
import UploadZone from "./UploadZone";
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
  const activeNlePlanReview = useEditorStore((s) => s.activeNlePlanReview);

  if (isRestoring) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background">
        <div className="text-muted-foreground text-sm">Restoring session…</div>
      </div>
    );
  }

  // No asset yet — upload landing. Header carries the branded logo + account menu.
  if (!asset || asset.status !== "ready") {
    return (
      <div className="min-h-screen flex flex-col bg-background">
        <header className="h-12 border-b border-border bg-card flex items-center px-4 gap-3 shrink-0">
          <div className="w-7 h-7 rounded-md bg-primary flex items-center justify-center">
            <Music className="w-3.5 h-3.5 text-primary-foreground" />
          </div>
          <h1 className="text-sm font-medium text-foreground flex-1">AI Audio Editor</h1>
          <UserMenu />
        </header>
        <UploadZone />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-background">
      {/* Header — logo + Toolbar (New/Undo/Redo/meta/Export) + UserMenu */}
      <header className="h-12 border-b border-border bg-card flex items-center px-4 gap-3 shrink-0">
        <div className="w-7 h-7 rounded-md bg-primary flex items-center justify-center shrink-0">
          <Music className="w-3.5 h-3.5 text-primary-foreground" />
        </div>
        <div className="flex-1 min-w-0">
          <Toolbar />
        </div>
        <UserMenu />
      </header>

      {/* Horizontal EditToolbar directly under the header, per the harvest.
          Hidden while in channel-edit mode — ChannelEditor renders its own
          per-channel op panel. */}
      {!channelEdit && <EditToolbar />}

      {/* Processing overlay */}
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
