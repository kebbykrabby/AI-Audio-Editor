import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { FileAudio, Loader2, Trash2, UploadCloud } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  deleteAsset,
  listAssets,
  pollUntilReady,
  uploadAudio,
  type AssetListItem,
} from "../api/assets";
import { ApiRequestError } from "../api/client";
import UserMenu from "../auth/UserMenu";
import { useEditorStore } from "../store/editorStore";
import { Music } from "lucide-react";

const MAX_SIZE = 100 * 1024 * 1024;
const ACCEPTED = [".wav", ".mp3"];

/** Format a file size in bytes as KB / MB with one decimal. */
function fmtSize(bytes: number | null | undefined): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function fmtDuration(sec: number | null | undefined): string {
  if (sec == null) return "";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/**
 * Landing page after sign-in. Two panels:
 *   - Big drop-target for a new upload → jumps into the editor when ready.
 *   - Grid of the user's existing projects (`GET /api/assets`) with delete
 *     button on hover (`DELETE /api/assets/:id`).
 */
export default function DashboardPage() {
  const navigate = useNavigate();
  const [dragOver, setDragOver] = useState(false);
  const setAssetReady = useEditorStore((s) => s.setAssetReady);
  const setUploading = useEditorStore((s) => s.setUploading);
  const isUploading = useEditorStore((s) => s.isUploading);

  const [assets, setAssets] = useState<AssetListItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const uploadIdRef = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const { assets } = await listAssets();
      setAssets(assets);
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load projects");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleFile = useCallback(
    async (file: File) => {
      const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
      if (!ACCEPTED.includes(ext)) {
        toast.error("Unsupported format. Please upload WAV or MP3.");
        return;
      }
      if (file.size > MAX_SIZE) {
        toast.error("File exceeds the 100 MB limit.");
        return;
      }
      const thisUpload = ++uploadIdRef.current;
      setUploading(true);
      try {
        const { assetId } = await uploadAudio(file);
        const asset = await pollUntilReady(assetId);
        if (thisUpload !== uploadIdRef.current) return;
        setAssetReady(asset);
        navigate("/editor");
      } catch (e: unknown) {
        if (thisUpload !== uploadIdRef.current) return;
        const msg =
          e instanceof ApiRequestError
            ? e.message
            : e instanceof Error
              ? e.message
              : "Upload failed";
        toast.error(msg);
      } finally {
        if (thisUpload === uploadIdRef.current) setUploading(false);
      }
    },
    [setAssetReady, setUploading, navigate],
  );

  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) void handleFile(file);
    },
    [handleFile],
  );

  const onFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) void handleFile(file);
    },
    [handleFile],
  );

  const openProject = (id: string) => {
    // Set as the persisted tip so useRestoreSession hydrates it on the editor
    // page, then navigate. `setAssetReady` isn't right here — we don't have
    // the ready Asset object; the editor's restore step will fetch it.
    try {
      localStorage.setItem("audioEditor.currentAssetId", id);
    } catch {
      // localStorage unavailable — proceed anyway; editor's restore returns null.
    }
    navigate("/editor");
  };

  const handleDelete = async (id: string, filename: string | null) => {
    if (!window.confirm(`Delete "${filename ?? "this project"}"? This cannot be undone.`)) return;
    try {
      await deleteAsset(id);
      setAssets((cur) => cur?.filter((a) => a.assetId !== id) ?? null);
      toast.success("Project deleted");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Delete failed");
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-30 h-14 border-b border-border bg-card/80 backdrop-blur-sm flex items-center px-4 gap-3">
        <div className="w-8 h-8 rounded-md bg-primary flex items-center justify-center">
          <Music className="w-4 h-4 text-primary-foreground" />
        </div>
        <h1 className="text-base font-semibold text-foreground">AI Audio Editor</h1>
        <div className="flex-1" />
        <UserMenu />
      </header>

      <main className="max-w-6xl mx-auto p-6 space-y-8">
        {/* Upload zone */}
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className={`block w-full p-12 rounded-2xl border-2 border-dashed cursor-pointer transition-colors text-center ${
            dragOver
              ? "border-primary bg-primary/5"
              : "border-border bg-card hover:border-primary/50 hover:bg-accent/40"
          }`}
        >
          {isUploading ? (
            <div className="flex flex-col items-center gap-2">
              <Loader2 className="w-8 h-8 text-primary animate-spin" />
              <p className="text-base font-medium">Processing…</p>
              <p className="text-sm text-muted-foreground">
                Extracting metadata and generating waveform
              </p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <UploadCloud className="w-10 h-10 text-muted-foreground" strokeWidth={1.5} />
              <p className="text-base font-medium">Drop audio file here</p>
              <p className="text-sm text-muted-foreground">
                or click to browse — WAV or MP3, up to 100 MB
              </p>
              <input
                type="file"
                accept=".wav,.mp3,audio/wav,audio/mpeg"
                onChange={onFileSelect}
                className="hidden"
              />
            </div>
          )}
        </label>

        {/* Project list */}
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Your projects {assets != null && `(${assets.length})`}
          </h2>

          {loadError && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              {loadError}
            </div>
          )}

          {assets == null ? (
            <div className="text-sm text-muted-foreground py-6">Loading…</div>
          ) : assets.length === 0 ? (
            <div className="text-sm text-muted-foreground py-6 text-center rounded-lg border border-dashed border-border bg-card">
              You haven't uploaded any projects yet. Drop a file above to get started.
            </div>
          ) : (
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {assets.map((a) => (
                <div
                  key={a.assetId}
                  className="group relative rounded-xl border border-border bg-card p-4 hover:border-primary/50 hover:shadow-sm transition-colors cursor-pointer"
                  onClick={() => openProject(a.assetId)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      openProject(a.assetId);
                    }
                  }}
                >
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                      <FileAudio className="w-5 h-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {a.filename ?? "Untitled"}
                      </p>
                      <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                        {fmtDuration(a.durationSec)}
                        {a.channels != null && (
                          <> · {a.channels === 2 ? "Stereo" : "Mono"}</>
                        )}
                        {a.sampleRate != null && <> · {a.sampleRate} Hz</>}
                      </p>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {fmtSize(a.fileSizeBytes)} · {fmtDate(a.createdAt)}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleDelete(a.assetId, a.filename);
                      }}
                      title="Delete project"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
