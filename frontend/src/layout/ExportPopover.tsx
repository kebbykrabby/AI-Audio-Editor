import { useState } from "react";
import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { enqueueExport, pollExport } from "../api/export";
import { ApiRequestError } from "../api/client";
import { useAuthStore } from "../store/authStore";
import { useEditorStore } from "../store/editorStore";
import EmailVerificationModal from "./EmailVerificationModal";

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

/**
 * Export button + params dialog + email-verification retry loop.
 *
 * Kept named `ExportPopover` for continuity even though the UI is now a real
 * modal Dialog (matches the harvested design). Behavior is unchanged:
 * enqueueExport → poll → download; on `EMAIL_VERIFICATION_REQUIRED`, show the
 * verify modal and re-run the export on success.
 */
export default function ExportPopover() {
  const asset = useEditorStore((s) => s.currentAsset());
  const channelEdit = useEditorStore((s) => s.channelEdit);
  const setError = useEditorStore((s) => s.setError);
  const user = useAuthStore((s) => s.user);

  const [open, setOpen] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [format, setFormat] = useState<Format>("wav");
  const [sampleRate, setSampleRate] = useState<SampleRate>("source");
  const [bitrate, setBitrate] = useState<Bitrate>(192);
  const [showVerifyModal, setShowVerifyModal] = useState(false);

  if (!asset) return null;

  const runExport = async () => {
    setIsExporting(true);
    try {
      const sr = sampleRate === "source" ? undefined : sampleRate;
      const br = format === "mp3" ? bitrate : undefined;
      const { exportId } = await enqueueExport(asset.assetId, format, sr, br);
      const res = await pollExport(exportId);
      if (!res.downloadUrl)
        throw new ApiRequestError("EXPORT_FAILED", "Export completed without a download URL", 0);
      const a = document.createElement("a");
      a.href = res.downloadUrl;
      a.download = `export.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setOpen(false);
    } catch (e: unknown) {
      if (e instanceof ApiRequestError && e.code === "EMAIL_VERIFICATION_REQUIRED") {
        setShowVerifyModal(true);
        return;
      }
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

  const handleExport = async () => {
    if (isExporting) return;
    await runExport();
  };

  const handleVerified = async () => {
    setShowVerifyModal(false);
    await runExport();
  };

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="h-8 gap-1.5"
        disabled={!!channelEdit}
        onClick={() => setOpen(true)}
        title="Export the current version"
      >
        <Download className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">Export</span>
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Export</DialogTitle>
            <DialogDescription>
              Download the current version of your audio.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div>
              <Label className="text-xs">Format</Label>
              <div className="mt-1 flex gap-2">
                {(["wav", "mp3"] as Format[]).map((f) => (
                  <Button
                    key={f}
                    type="button"
                    variant={format === f ? "default" : "secondary"}
                    className="flex-1"
                    onClick={() => setFormat(f)}
                  >
                    {f.toUpperCase()}
                  </Button>
                ))}
              </div>
            </div>

            <div>
              <Label className="text-xs">Sample rate</Label>
              <Select
                value={String(sampleRate)}
                onValueChange={(v) =>
                  setSampleRate(v === "source" ? "source" : (Number(v) as SampleRate))
                }
              >
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SAMPLE_RATE_OPTIONS.map((opt) => (
                    <SelectItem key={String(opt.value)} value={String(opt.value)}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className={`text-xs ${format === "mp3" ? "" : "text-muted-foreground/60"}`}>
                Bitrate{format === "wav" && " (MP3 only)"}
              </Label>
              <Select
                value={String(bitrate)}
                onValueChange={(v) => setBitrate(Number(v) as Bitrate)}
                disabled={format !== "mp3"}
              >
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {BITRATE_OPTIONS.map((b) => (
                    <SelectItem key={b} value={String(b)}>
                      {b} kbps
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={isExporting}>
              Cancel
            </Button>
            <Button onClick={handleExport} disabled={isExporting}>
              {isExporting ? "Exporting…" : "Download"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {showVerifyModal && user?.email && (
        <EmailVerificationModal
          email={user.email}
          onClose={() => setShowVerifyModal(false)}
          onVerified={handleVerified}
        />
      )}
    </>
  );
}
