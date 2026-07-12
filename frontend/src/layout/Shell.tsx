import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { Music } from "lucide-react";

import UserMenu from "../auth/UserMenu";
import { useEditorStore } from "../store/editorStore";
import { useRestoreSession } from "../store/useRestoreSession";
import ResizeHandle from "./ResizeHandle";
import SidePanel from "./SidePanel";
import Toolbar from "./Toolbar";
import TransportBar from "./TransportBar";
import WaveformPlayer from "../audio/WaveformPlayer";
import WaveformErrorBoundary from "../audio/WaveformErrorBoundary";
import EditToolbar from "../editor/EditToolbar";
import ChannelEditor from "../editor/ChannelEditor";

type Tab = "history" | "fillers" | "censor" | "ai";

const SIDE_WIDTH_KEY = "audioEditor.sidePanelWidth";
const DEFAULT_SIDE_WIDTH = 320;

function readSideWidth(): number {
  try {
    const raw = localStorage.getItem(SIDE_WIDTH_KEY);
    if (!raw) return DEFAULT_SIDE_WIDTH;
    const n = Number(raw);
    return Number.isFinite(n) && n >= 240 && n <= 640 ? n : DEFAULT_SIDE_WIDTH;
  } catch {
    return DEFAULT_SIDE_WIDTH;
  }
}

/**
 * Editor route (`/editor`). Two-column layout:
 *   - Left: EditToolbar strip + waveform card + TransportBar dock (all `flex-1`)
 *   - Right: SidePanel with 4 tabs (History / Fillers / Censor / AI) + a
 *     collapse rail
 *
 * When the user has no ready asset (fresh session, failed restore, deleted
 * project) we send them back to the Dashboard.
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

  const [tab, setTab] = useState<Tab>("history");
  const [sideCollapsed, setSideCollapsed] = useState(false);
  const [sideWidth, setSideWidth] = useState<number>(readSideWidth);

  // Persist width changes so the layout survives a reload.
  useEffect(() => {
    try {
      localStorage.setItem(SIDE_WIDTH_KEY, String(sideWidth));
    } catch {
      // localStorage unavailable — persistence is best-effort.
    }
  }, [sideWidth]);

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
    return <Navigate to="/" replace />;
  }

  return (
    <div className="h-screen flex flex-col bg-background overflow-hidden">
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
          className="px-4 py-2 border-b border-destructive/30 bg-destructive/10 text-destructive text-sm flex justify-between items-center shrink-0"
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
        <div className="px-4 py-2 border-b bg-yellow-100 text-yellow-900 border-yellow-300 text-sm flex justify-between items-center shrink-0">
          <span>{warning}</span>
          <button
            onClick={() => setWarning(null)}
            className="text-yellow-700 hover:text-yellow-900 text-xs uppercase tracking-wide"
          >
            dismiss
          </button>
        </div>
      )}

      {/* Two-column body */}
      <div className="flex-1 flex overflow-hidden">
        {channelEdit ? (
          <div className="flex-1 p-4 overflow-auto">
            <ChannelEditor />
          </div>
        ) : (
          <>
            {/* Left: waveform + transport */}
            <div className="flex-1 flex flex-col min-w-0">
              <div className="flex-1 p-4 min-h-0">
                <WaveformErrorBoundary onReset={() => setError(null)}>
                  <WaveformPlayer />
                </WaveformErrorBoundary>
              </div>
              <div className="px-4 pb-4">
                <TransportBar />
              </div>
            </div>

            {/* Draggable divider — hidden when the sidebar is collapsed. */}
            {!sideCollapsed && (
              <ResizeHandle width={sideWidth} onWidthChange={setSideWidth} />
            )}

            {/* Right: sidebar with tabs */}
            <SidePanel
              tab={tab}
              setTab={setTab}
              collapsed={sideCollapsed}
              setCollapsed={setSideCollapsed}
              width={sideWidth}
            />
          </>
        )}
      </div>
    </div>
  );
}
