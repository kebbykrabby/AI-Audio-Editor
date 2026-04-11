import { useState } from "react";
import { executeOperation } from "../api/operations";
import { useEditorStore } from "../store/editorStore";

type OpType = "trim" | "delete" | "fade_in" | "fade_out" | "gain" | "normalize";

const DURATION_CHANGING: OpType[] = ["trim", "delete"];

export default function OperationPanel() {
  const asset = useEditorStore((s) => s.currentAsset());
  const selection = useEditorStore((s) => s.selection);
  const pushAsset = useEditorStore((s) => s.pushAsset);
  const setProcessing = useEditorStore((s) => s.setProcessing);
  const setError = useEditorStore((s) => s.setError);
  const setWarning = useEditorStore((s) => s.setWarning);
  const isProcessing = useEditorStore((s) => s.isProcessing);

  const [fadeDuration, setFadeDuration] = useState(1.0);
  const [fadeCurve, setFadeCurve] = useState<"linear" | "exponential">("linear");
  const [gainDb, setGainDb] = useState(0);
  const [targetDb, setTargetDb] = useState(-1);

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
    return null;
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
      pushAsset(res.asset, durationChanged);
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

      {!selection && (
        <p className="text-xs text-slate-500">Select a region on the waveform to use Trim and Delete</p>
      )}
    </div>
  );
}
