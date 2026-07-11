import { useState } from "react";
import {
  ArrowLeftRight,
  Gauge,
  Headphones,
  RotateCcw,
  Scissors,
  Timer,
  Trash2,
  TrendingUp,
  Volume2,
  VolumeX,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { useEditorStore } from "../store/editorStore";
import { useEditOperation } from "./useEditOperation";

type FadeDirection = "in" | "out";
type FadeCurve = "linear" | "exponential";
type ChannelOp = "left" | "right" | "swap" | "mono";

/**
 * Horizontal icon-button toolbar mounted directly under the app header.
 *
 * Each button either fires an operation immediately (Trim, Delete, Reverse) or
 * opens a Dialog for parameter input (Fade, Volume, Normalize, Silence, Speed,
 * Stereo). Every dispatch goes through `useEditOperation.runOp` so the
 * enqueue → poll → apply pipeline stays identical to before the reskin.
 */
export default function EditToolbar() {
  const asset = useEditorStore((s) => s.currentAsset());
  const selection = useEditorStore((s) => s.selection);
  const isProcessing = useEditorStore((s) => s.isProcessing);
  const channelEdit = useEditorStore((s) => s.channelEdit);
  const { runOp } = useEditOperation();

  const [fadeOpen, setFadeOpen] = useState(false);
  const [fadeDir, setFadeDir] = useState<FadeDirection>("in");
  const [fadeCurve, setFadeCurve] = useState<FadeCurve>("linear");
  const [fadeDurationSec, setFadeDurationSec] = useState(1.0);

  const [gainOpen, setGainOpen] = useState(false);
  const [gainDb, setGainDb] = useState(0);

  const [normalizeOpen, setNormalizeOpen] = useState(false);
  const [normalizeTargetDb, setNormalizeTargetDb] = useState(-1);

  const [silenceOpen, setSilenceOpen] = useState(false);
  const [silenceThresholdDb, setSilenceThresholdDb] = useState(-40);
  const [silenceMinMs, setSilenceMinMs] = useState(500);

  const [speedOpen, setSpeedOpen] = useState(false);
  const [speedRate, setSpeedRate] = useState(1.0);

  const [channelOpen, setChannelOpen] = useState(false);
  const [channelOp, setChannelOp] = useState<ChannelOp>("mono");

  if (!asset) return null;

  const hasSelection = !!selection && selection.endSec - selection.startSec > 0.01;
  const isStereo = (asset.channels ?? 1) > 1;

  const runAndClose = (
    op: () => Promise<void> | void,
    setOpen: (v: boolean) => void,
  ) => {
    setOpen(false);
    void op();
  };

  return (
    <div className="flex items-center gap-1 flex-wrap px-4 py-2 bg-card border-b border-border">
      {/* Trim / Delete — need a selection */}
      <Button
        variant="ghost"
        size="sm"
        className="h-8 gap-1.5 text-xs"
        disabled={!hasSelection || isProcessing}
        onClick={() =>
          selection &&
          void runOp("trim", {
            start_sec: selection.startSec,
            end_sec: selection.endSec,
          })
        }
        title="Keep only the selection"
      >
        <Scissors className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">Trim</span>
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="h-8 gap-1.5 text-xs"
        disabled={!hasSelection || isProcessing}
        onClick={() =>
          selection &&
          void runOp("delete", {
            start_sec: selection.startSec,
            end_sec: selection.endSec,
          })
        }
        title="Remove the selection"
      >
        <Trash2 className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">Delete</span>
      </Button>

      <div className="w-px h-6 bg-border mx-1" />

      {/* Fade */}
      <Button
        variant="ghost"
        size="sm"
        className="h-8 gap-1.5 text-xs"
        disabled={isProcessing}
        onClick={() => setFadeOpen(true)}
        title="Fade in / out"
      >
        <TrendingUp className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">Fade</span>
      </Button>

      {/* Volume / Gain */}
      <Button
        variant="ghost"
        size="sm"
        className="h-8 gap-1.5 text-xs"
        disabled={isProcessing}
        onClick={() => {
          setGainDb(0);
          setGainOpen(true);
        }}
        title="Adjust volume"
      >
        <Volume2 className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">Volume</span>
      </Button>

      {/* Normalize */}
      <Button
        variant="ghost"
        size="sm"
        className="h-8 gap-1.5 text-xs"
        disabled={isProcessing}
        onClick={() => setNormalizeOpen(true)}
        title="Normalize to a target level"
      >
        <Gauge className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">Normalize</span>
      </Button>

      <div className="w-px h-6 bg-border mx-1" />

      {/* Reverse */}
      <Button
        variant="ghost"
        size="sm"
        className="h-8 gap-1.5 text-xs"
        disabled={isProcessing}
        onClick={() => void runOp("reverse", {})}
        title="Reverse the audio"
      >
        <RotateCcw className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">Reverse</span>
      </Button>

      {/* Remove silence */}
      <Button
        variant="ghost"
        size="sm"
        className="h-8 gap-1.5 text-xs"
        disabled={isProcessing}
        onClick={() => setSilenceOpen(true)}
        title="Remove silent gaps"
      >
        <VolumeX className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">Silence</span>
      </Button>

      {/* Speed */}
      <Button
        variant="ghost"
        size="sm"
        className="h-8 gap-1.5 text-xs"
        disabled={isProcessing}
        onClick={() => {
          setSpeedRate(1.0);
          setSpeedOpen(true);
        }}
        title="Change playback speed"
      >
        <Timer className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">Speed</span>
      </Button>

      {isStereo && !channelEdit && (
        <>
          <div className="w-px h-6 bg-border mx-1" />
          <Button
            variant="ghost"
            size="sm"
            className="h-8 gap-1.5 text-xs"
            disabled={isProcessing}
            onClick={() => setChannelOpen(true)}
            title="Stereo tools"
          >
            <Headphones className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Stereo</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 gap-1.5 text-xs"
            disabled={isProcessing}
            onClick={() => void runOp("split_channels", {})}
            title="Split into left / right for independent editing"
          >
            <ArrowLeftRight className="w-3.5 h-3.5" />
            <span className="hidden lg:inline">Split &amp; Edit</span>
          </Button>
        </>
      )}

      {/* --- Fade dialog --- */}
      <Dialog open={fadeOpen} onOpenChange={setFadeOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Fade</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label>Direction</Label>
              <Select value={fadeDir} onValueChange={(v) => setFadeDir(v as FadeDirection)}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="in">Fade In</SelectItem>
                  <SelectItem value="out">Fade Out</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Curve</Label>
              <Select value={fadeCurve} onValueChange={(v) => setFadeCurve(v as FadeCurve)}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="linear">Linear</SelectItem>
                  <SelectItem value="exponential">Exponential</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Duration (seconds)</Label>
              <Input
                type="number"
                min={0.1}
                step={0.1}
                value={fadeDurationSec}
                onChange={(e) => setFadeDurationSec(Number(e.target.value) || 0)}
                className="mt-1"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFadeOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                runAndClose(
                  () =>
                    runOp(fadeDir === "in" ? "fade_in" : "fade_out", {
                      duration_sec: fadeDurationSec,
                      curve: fadeCurve,
                    }),
                  setFadeOpen,
                )
              }
            >
              Apply
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* --- Volume / gain dialog --- */}
      <Dialog open={gainOpen} onOpenChange={setGainOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Adjust Volume</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label>
                Volume change: {gainDb > 0 ? "+" : ""}
                {gainDb} dB
              </Label>
              <Slider
                value={[gainDb]}
                onValueChange={([v]) => setGainDb(v)}
                min={-20}
                max={20}
                step={0.5}
                className="mt-2"
              />
              <div className="flex justify-between text-xs text-muted-foreground mt-1">
                <span>-20 dB (quieter)</span>
                <span>+20 dB (louder)</span>
              </div>
            </div>
            {gainDb > 6 && (
              <p className="text-xs text-yellow-800 bg-yellow-100 rounded-md p-2">
                Large volume increases may cause clipping distortion.
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGainOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => runAndClose(() => runOp("gain", { gain_db: gainDb }), setGainOpen)}>
              Apply
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* --- Normalize dialog --- */}
      <Dialog open={normalizeOpen} onOpenChange={setNormalizeOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Normalize</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label>Target peak level: {normalizeTargetDb} dB</Label>
              <Slider
                value={[normalizeTargetDb]}
                onValueChange={([v]) => setNormalizeTargetDb(v)}
                min={-12}
                max={0}
                step={0.5}
                className="mt-2"
              />
              <p className="text-xs text-muted-foreground mt-1">
                -1 dB is standard for podcasts. 0 dB is the maximum without clipping.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNormalizeOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                runAndClose(
                  () => runOp("normalize", { target_db: normalizeTargetDb }),
                  setNormalizeOpen,
                )
              }
            >
              Apply
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* --- Remove silence dialog --- */}
      <Dialog open={silenceOpen} onOpenChange={setSilenceOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Remove Silent Gaps</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label>Silence threshold: {silenceThresholdDb} dB</Label>
              <Slider
                value={[silenceThresholdDb]}
                onValueChange={([v]) => setSilenceThresholdDb(v)}
                min={-60}
                max={-10}
                step={1}
                className="mt-2"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Lower = only detect very quiet sections. Higher = more aggressive.
              </p>
            </div>
            <div>
              <Label>Minimum gap: {silenceMinMs} ms</Label>
              <Slider
                value={[silenceMinMs]}
                onValueChange={([v]) => setSilenceMinMs(v)}
                min={50}
                max={2000}
                step={50}
                className="mt-2"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Only remove gaps longer than this. Short pauses feel natural in speech.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSilenceOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                runAndClose(
                  () =>
                    runOp("remove_silence", {
                      threshold_db: silenceThresholdDb,
                      min_silence_sec: silenceMinMs / 1000,
                    }),
                  setSilenceOpen,
                )
              }
            >
              Apply
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* --- Speed dialog --- */}
      <Dialog open={speedOpen} onOpenChange={setSpeedOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Change Speed</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label>Speed: {speedRate.toFixed(2)}×</Label>
              <Slider
                value={[speedRate]}
                onValueChange={([v]) => setSpeedRate(v)}
                min={0.5}
                max={2.0}
                step={0.05}
                className="mt-2"
              />
              <div className="flex justify-between text-xs text-muted-foreground mt-1">
                <span>0.5× (slower)</span>
                <span>1.0×</span>
                <span>2.0× (faster)</span>
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                This is a time-domain rate change — very extreme values may affect quality.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSpeedOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => runAndClose(() => runOp("speed", { factor: speedRate }), setSpeedOpen)}
            >
              Apply
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* --- Stereo tools dialog --- */}
      <Dialog open={channelOpen} onOpenChange={setChannelOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Stereo Tools</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label>Operation</Label>
              <Select value={channelOp} onValueChange={(v) => setChannelOp(v as ChannelOp)}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="left">Extract left channel</SelectItem>
                  <SelectItem value="right">Extract right channel</SelectItem>
                  <SelectItem value="swap">Swap left &amp; right</SelectItem>
                  <SelectItem value="mono">Mix down to mono</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setChannelOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                runAndClose(() => {
                  if (channelOp === "left" || channelOp === "right") {
                    return runOp("extract_channel", { channel: channelOp });
                  }
                  if (channelOp === "swap") return runOp("swap_channels", {});
                  return runOp("mono_mixdown", {});
                }, setChannelOpen)
              }
            >
              Apply
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
