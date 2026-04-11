import { useEditorStore } from "../store/editorStore";

export default function SelectionInfo() {
  const selection = useEditorStore((s) => s.selection);
  const setSelection = useEditorStore((s) => s.setSelection);
  const asset = useEditorStore((s) => s.currentAsset());

  if (!selection || !asset) return null;

  const maxDur = asset.durationSec ?? 0;

  const updateStart = (v: string) => {
    const n = parseFloat(v);
    if (!isNaN(n) && n >= 0 && n < selection.endSec) {
      setSelection({ startSec: n, endSec: selection.endSec });
    }
  };

  const updateEnd = (v: string) => {
    const n = parseFloat(v);
    if (!isNaN(n) && n > selection.startSec && n <= maxDur) {
      setSelection({ startSec: selection.startSec, endSec: n });
    }
  };

  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-slate-500">Selection:</span>
      <input
        type="number"
        step={0.1}
        min={0}
        max={selection.endSec}
        value={selection.startSec.toFixed(2)}
        onChange={(e) => updateStart(e.target.value)}
        className="param-input w-24"
      />
      <span className="text-slate-500">to</span>
      <input
        type="number"
        step={0.1}
        min={selection.startSec}
        max={maxDur}
        value={selection.endSec.toFixed(2)}
        onChange={(e) => updateEnd(e.target.value)}
        className="param-input w-24"
      />
      <span className="text-slate-500">
        ({(selection.endSec - selection.startSec).toFixed(2)}s)
      </span>
    </div>
  );
}
