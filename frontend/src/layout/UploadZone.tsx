import { useCallback, useRef, useState, type DragEvent } from "react";
import { Loader2, UploadCloud } from "lucide-react";
import { uploadAudio, pollUntilReady } from "../api/assets";
import { ApiRequestError } from "../api/client";
import { useEditorStore } from "../store/editorStore";

const MAX_SIZE = 100 * 1024 * 1024;
const ACCEPTED = [".wav", ".mp3"];

// Map backend error codes to friendlier messages. Falls back to the server message.
function friendlyMessage(err: unknown): string {
  if (err instanceof ApiRequestError) {
    switch (err.code) {
      case "PROCESSING_TIMEOUT":
        return "Processing is taking longer than expected. Try a smaller file.";
      case "INVALID_FILE":
        return err.message || "The file format isn't supported.";
      case "SERVER_RESTART":
        return "The server restarted while processing your file. Please try again.";
      case "PROCESSING_FAILED":
        return err.message || "Processing failed. The file may be corrupted.";
      default:
        return err.message;
    }
  }
  return err instanceof Error ? err.message : "Upload failed";
}

export default function UploadZone() {
  const [dragOver, setDragOver] = useState(false);
  const setAssetReady = useEditorStore((s) => s.setAssetReady);
  const setUploading = useEditorStore((s) => s.setUploading);
  const setError = useEditorStore((s) => s.setError);
  const isUploading = useEditorStore((s) => s.isUploading);
  const error = useEditorStore((s) => s.error);
  const uploadIdRef = useRef(0);

  const handleFile = useCallback(async (file: File) => {
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPTED.includes(ext)) {
      setError("Unsupported format. Please upload WAV or MP3.");
      return;
    }
    if (file.size > MAX_SIZE) {
      setError("File exceeds 100MB limit.");
      return;
    }

    const thisUpload = ++uploadIdRef.current;
    setError(null);
    setUploading(true);
    try {
      const { assetId } = await uploadAudio(file);
      const asset = await pollUntilReady(assetId);
      if (thisUpload !== uploadIdRef.current) return; // stale upload
      setAssetReady(asset);
    } catch (e: unknown) {
      if (thisUpload !== uploadIdRef.current) return;
      setError(friendlyMessage(e));
    } finally {
      if (thisUpload === uploadIdRef.current) setUploading(false);
    }
  }, [setAssetReady, setUploading, setError]);

  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const onFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  return (
    <div className="flex items-center justify-center flex-1 p-8">
      <label
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`
          w-full max-w-2xl p-16 rounded-2xl border-2 border-dashed text-center transition-colors cursor-pointer flex flex-col items-center gap-3
          ${dragOver
            ? "border-primary bg-primary/5"
            : "border-border bg-card hover:border-primary/50 hover:bg-accent/40"
          }
        `}
      >
        {isUploading ? (
          <>
            <Loader2 className="w-8 h-8 text-primary animate-spin" />
            <div className="text-lg font-medium text-foreground">Processing…</div>
            <div className="text-sm text-muted-foreground">
              Extracting metadata and generating waveform
            </div>
          </>
        ) : (
          <>
            <UploadCloud className="w-10 h-10 text-muted-foreground" strokeWidth={1.5} />
            <div className="text-lg font-medium text-foreground">Drop audio file here</div>
            <div className="text-sm text-muted-foreground">
              or click to browse — WAV or MP3, up to 100 MB
            </div>
            <input
              type="file"
              accept=".wav,.mp3,audio/wav,audio/mpeg"
              onChange={onFileSelect}
              className="hidden"
            />
          </>
        )}
        {error && (
          <div className="mt-2 text-destructive text-sm">{error}</div>
        )}
      </label>
    </div>
  );
}
