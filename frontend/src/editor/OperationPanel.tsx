import { useState } from "react";
import { executeOperation } from "../api/operations";
import { useEditorStore } from "../store/editorStore";

type OpType = "trim" | "delete" | "fade_in" | "fade_out" | "gain" | "normalize"
  | "reverse" | "remove_silence" | "extract_channel" | "swap_channels" | "mono_mixdown" | "speed";

const DURATION_CHANGING: OpType[] = ["trim", "delete", "remove_silence", "speed"];

export default function OperationPanel() {
  const asset = useEditorStore((s) => s.currentAsset());
  const selection = useEditorStore((s) => s.selection);
  const pushAsset = useEditorStore((s) => s.pushAsset);
  const setProcessing = useEditorStore((s) => s.setProcessing);
  const setError = useEditorStore((s) => s.setError);
  const setWarning = useEditorStore((s) => s.setWarning);
  const isProcessing = useEditorStore((s) => s.isProcessing);
  const channelEdit = useEditorStore((s) => s.channelEdit);
  const updateChannelAsset = useEditorStore((s) => s.updateChannelAsset);
  const enterChannelEdit = useEditorStore((s) => s.enterChannelEdit);

  const [fadeDuration, setFadeDuration] = useState(1.0);
  const [fadeCurve, setFadeCurve] = useState<"linear" | "exponential">("linear");
  const [gainDb, setGainDb] = useState(0);
  const [targetDb, setTargetDb] = useState(-1);
  const [speedFactor, setSpeedFactor] = useState(1.0);
  const [silenceThreshold, setSilenceThreshold] = useState(-40);
  const [silenceMinDuration, setSilenceMinDuration] = useState(0.5);
  const [extractCh, setExtractCh] = useState<"left" | "right">("left");

  if (!asset) return null;

  const validate = (type: OpType, params: Record<string, unknown>): string | null => {
    const duration = asset.durationSec ?? 0;
    if (type === "trim" || type === "delete") {
      const start = params.start_sec as number;
      const end = params.end_sec as number;
      if (start >= end) return "Start must be less than end";
      if (end > duration) return "End exceeds audio duration";
      if (type === "delete" && start <= 0 && end >= duration)
        return "Cannot delete the entire file";
    }
    if (type === "fade_in" || type === "fade_out") {
      if ((params.duration_sec as number) > duration)
        return "Fade duration exceeds audio duration";
    }
    if (type === "speed") {
      const factor = params.factor as number;
      if (factor < 0.25 || factor > 4.0) return "Speed must be between 0.25x and 4.0x";
    }
    if (type === "remove_silence") {
      const threshold = params.threshold_db as number;
      if (threshold < -80 || threshold > 0) return "Threshold must be between -80 and 0 dB";
    }
    return null;
  };

  const handleSplitChannels = async () => {
    if (!asset) return;
    setProcessing(true);
    setError(null);
    try {
      const res = await executeOperation("split_channels", asset.assetId, {});
      if (res.secondaryAsset) {
        enterChannelEdit(asset.assetId, res.asset, res.secondaryAsset);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Split failed");
    } finally {
      setProcessing(false);
    }
  };

  const runOp = async (type: OpType, params: Record<string, unknown>) => {
    const validationError = validate(type, params);
    if (validationError) {
      setError(validationError);
      return;
    }
    setProcessing(true);
    setError(null);
    try {
      const res = await executeOperation(type, asset.assetId, params);
      const durationChanged = DURATION_CHANGING.includes(type);
      if (channelEdit) {
        updateChannelAsset(channelEdit.activeChannel, res.asset);
      } else {
        pushAsset(res.asset, durationChanged);
      }
      if (res.warning) setWarning(res.warning);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Operation failed");
    } finally {
      setProcessing(false);
    }
  };

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wide">Operations</h3>

      {/* Selection-based ops */}
      <div className="flex flex-wrap gap-2">
        <button
          disabled={isProcessing || !selection}
          onClick={() => selection && runOp("trim", { start_sec: selection.startSec, end_sec: selection.endSec })}
          className="op-btn"
          title="Keep selected range, discard the rest"
        >
          Trim to Selection
        </button>
        <button
          disabled={isProcessing || !selection}
          onClick={() => selection && runOp("delete", { start_sec: selection.startSec, end_sec: selection.endSec })}
          className="op-btn"
          title="Remove selected range, keep the rest"
        >
          Delete Selection
        </button>
      </div>

      {/* Fade */}
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="text-xs text-slate-500">Duration (s)</label>
          <input
            type="number"
            min={0.1}
            step={0.1}
            value={fadeDuration}
            onChange={(e) => setFadeDuration(Number(e.target.value))}
            className="param-input w-20"
          />
        </div>
        <div>
          <label className="text-xs text-slate-500">Curve</label>
          <select value={fadeCurve} onChange={(e) => setFadeCurve(e.target.value as any)} className="param-input">
            <option value="linear">Linear</option>
            <option value="exponential">Exponential</option>
          </select>
        </div>
        <button disabled={isProcessing} onClick={() => runOp("fade_in", { duration_sec: fadeDuration, curve: fadeCurve })} className="op-btn">
          Fade In
        </button>
        <button disabled={isProcessing} onClick={() => runOp("fade_out", { duration_sec: fadeDuration, curve: fadeCurve })} className="op-btn">
          Fade Out
        </button>
      </div>

      {/* Gain */}
      <div className="flex items-end gap-2">
        <div>
          <label className="text-xs text-slate-500">Gain (dB)</label>
          <input
            type="number"
            min={-60}
            max={24}
            step={1}
            value={gainDb}
            onChange={(e) => setGainDb(Number(e.target.value))}
            className="param-input w-24"
          />
        </div>
        <input
          type="range"
          min={-60}
          max={24}
          value={gainDb}
          onChange={(e) => setGainDb(Number(e.target.value))}
          className="w-40"
        />
        <button disabled={isProcessing} onClick={() => runOp("gain", { gain_db: gainDb })} className="op-btn">
          Apply Gain
        </button>
      </div>

      {/* Normalize */}
      <div className="flex items-end gap-2">
        <div>
          <label className="text-xs text-slate-500">Target (dB)</label>
          <input
            type="number"
            min={-60}
            max={0}
            step={1}
            value={targetDb}
            onChange={(e) => setTargetDb(Number(e.target.value))}
            className="param-input w-24"
          />
        </div>
        <button disabled={isProcessing} onClick={() => runOp("normalize", { target_db: targetDb })} className="op-btn">
          Normalize
        </button>
      </div>

      {/* Transform */}
      <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mt-4">Transform</h4>
      <div className="flex flex-wrap items-end gap-2">
        <button disabled={isProcessing} onClick={() => runOp("reverse", {})} className="op-btn">
          Reverse
        </button>
        <div>
          <label className="text-xs text-slate-500">Speed</label>
          <input
            type="number"
            min={0.25}
            max={4.0}
            step={0.25}
            value={speedFactor}
            onChange={(e) => setSpeedFactor(Number(e.target.value))}
            className="param-input w-20"
          />
        </div>
        <input
          type="range"
          min={0.25}
          max={4.0}
          step={0.25}
          value={speedFactor}
          onChange={(e) => setSpeedFactor(Number(e.target.value))}
          className="w-32"
        />
        <span className="text-xs text-slate-400">{speedFactor}x</span>
        <button disabled={isProcessing} onClick={() => runOp("speed", { factor: speedFactor })} className="op-btn">
          Apply Speed
        </button>
      </div>

      {/* Silence Removal */}
      <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mt-4">Silence Removal</h4>
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="text-xs text-slate-500">Threshold (dB)</label>
          <input
            type="number"
            min={-80}
            max={0}
            step={1}
            value={silenceThreshold}
            onChange={(e) => setSilenceThreshold(Number(e.target.value))}
            className="param-input w-20"
          />
        </div>
        <div>
          <label className="text-xs text-slate-500">Min Duration (s)</label>
          <input
            type="number"
            min={0.1}
            max={10}
            step={0.1}
            value={silenceMinDuration}
            onChange={(e) => setSilenceMinDuration(Number(e.target.value))}
            className="param-input w-20"
          />
        </div>
        <button
          disabled={isProcessing}
          onClick={() => runOp("remove_silence", { threshold_db: silenceThreshold, min_silence_sec: silenceMinDuration })}
          className="op-btn"
        >
          Remove Silence
        </button>
      </div>

      {/* Channel Operations — only for stereo, hide in channel edit mode */}
      {asset.channels === 2 && !channelEdit && (
        <>
          <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mt-4">Channel Operations</h4>
          <div className="flex flex-wrap items-end gap-2">
            <button disabled={isProcessing} onClick={handleSplitChannels} className="op-btn">
              Split &amp; Edit Channels
            </button>
            <div>
              <label className="text-xs text-slate-500">Channel</label>
              <select value={extractCh} onChange={(e) => setExtractCh(e.target.value as "left" | "right")} className="param-input">
                <option value="left">Left</option>
                <option value="right">Right</option>
              </select>
            </div>
            <button disabled={isProcessing} onClick={() => runOp("extract_channel", { channel: extractCh })} className="op-btn">
              Extract Channel
            </button>
            <button disabled={isProcessing} onClick={() => runOp("swap_channels", {})} className="op-btn">
              Swap Channels
            </button>
            <button disabled={isProcessing} onClick={() => runOp("mono_mixdown", {})} className="op-btn">
              Mono Mixdown
            </button>
          </div>
        </>
      )}

      {!selection && (
        <p className="text-xs text-slate-500 mt-2">Select a region on the waveform to use Trim and Delete</p>
      )}
    </div>
  );
}
