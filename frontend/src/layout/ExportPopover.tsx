import { useEffect, useRef, useState } from "react";
import { enqueueExport, pollExport } from "../api/export";
import { useEditorStore } from "../store/editorStore";
import { ApiRequestError } from "../api/client";

type Format = "wav" | "mp3";
type SampleRate = "source" | 22050 | 44100 | 48000;
type Bitrate = 128 | 192 | 256 | 320;

const SAMPLE_RATE_OPTIONS: { value: SampleRate; label: string }[] = [
  { value: "source", label: "Source (match input)" },
  { value: 22050, label: "22,050 Hz" },
  { value: 44100, label: "44,100 Hz" },
  { value: 48000, label: "48,000 Hz" },
];

const BITRATE_OPTIONS: Bitrate[] = [128, 192, 256, 320];

export default function ExportPopover() {
  const asset = useEditorStore((s) => s.currentAsset());
  const channelEdit = useEditorStore((s) => s.channelEdit);
  const setError = useEditorStore((s) => s.setError);

  const [open, setOpen] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [format, setFormat] = useState<Format>("wav");
  const [sampleRate, setSampleRate] = useState<SampleRate>("source");
  const [bitrate, setBitrate] = useState<Bitrate>(192);

  const rootRef = useRef<HTMLDivElement>(null);

  // Close on outside click and Escape
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.code === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const handleExport = async () => {
    if (!asset || isExporting) return;
    setIsExporting(true);
    try {
      const sr = sampleRate === "source" ? undefined : sampleRate;
      const br = format === "mp3" ? bitrate : undefined;
      const { exportId } = await enqueueExport(asset.assetId, format, sr, br);
      const res = await pollExport(exportId);
      if (!res.downloadUrl) throw new ApiRequestError("EXPORT_FAILED", "Export completed without a download URL", 0);
      const a = document.createElement("a");
      a.href = res.downloadUrl;
      a.download = `export.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setOpen(false);
    } catch (e: unknown) {
      const msg =
        e instanceof ApiRequestError
          ? `${e.code}: ${e.message}`
          : e instanceof Error
            ? e.message
            : "Export failed";
      setError(msg);
    } finally {
      setIsExporting(false);
    }
  };

  if (!asset) return null;

  return (
    <div ref={rootRef} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={!!channelEdit}
        className="toolbar-btn"
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        Export…
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Export options"
          className="absolute right-0 top-full mt-2 w-72 bg-slate-800 border border-slate-600 rounded-lg shadow-xl p-4 z-20"
        >
          <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
            Export
          </h4>

          {/* Format */}
          <div className="mb-3">
            <label className="text-xs text-slate-500 block mb-1">Format</label>
            <div className="flex gap-2">
              {(["wav", "mp3"] as Format[]).map((f) => (
                <button
                  key={f}
                  onClick={() => setFormat(f)}
                  className={`flex-1 px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                    format === f
                      ? "bg-blue-600 text-white"
                      : "bg-slate-700 text-slate-300 hover:bg-slate-600"
                  }`}
                >
                  {f.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {/* Sample rate */}
          <div className="mb-3">
            <label className="text-xs text-slate-500 block mb-1">Sample rate</label>
            <select
              value={String(sampleRate)}
              onChange={(e) =>
                setSampleRate(e.target.value === "source" ? "source" : (Number(e.target.value) as SampleRate))
              }
              className="param-input w-full"
            >
              {SAMPLE_RATE_OPTIONS.map((opt) => (
                <option key={String(opt.value)} value={String(opt.value)}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Bitrate — MP3 only */}
          <div className="mb-4">
            <label
              className={`text-xs block mb-1 ${
                format === "mp3" ? "text-slate-500" : "text-slate-600"
              }`}
            >
              Bitrate {format === "wav" && <span className="text-slate-600">(MP3 only)</span>}
            </label>
            <select
              value={bitrate}
              onChange={(e) => setBitrate(Number(e.target.value) as Bitrate)}
              disabled={format !== "mp3"}
              className="param-input w-full disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {BITRATE_OPTIONS.map((b) => (
                <option key={b} value={b}>
                  {b} kbps
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={handleExport}
            disabled={isExporting}
            className="w-full px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed rounded text-sm text-white font-medium transition-colors"
          >
            {isExporting ? "Exporting…" : "Download"}
          </button>
        </div>
      )}
    </div>
  );
}
