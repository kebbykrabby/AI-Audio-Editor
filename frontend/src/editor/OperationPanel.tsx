import { useEffect, useRef, useState } from "react";
import { detectFillers, detectProfanity } from "../api/ai";
import { generateNlePlan } from "../api/nle";
import CensorshipSettingsModal from "./CensorshipSettingsModal";
import { ApiRequestError } from "../api/client";
import { enqueueOperation, pollOperation } from "../api/operations";
import { useEditorStore } from "../store/editorStore";
import type { OperationResponse } from "../store/types";

type OpType =
  | "trim"
  | "delete"
  | "fade_in"
  | "fade_out"
  | "gain"
  | "normalize"
  | "reverse"
  | "remove_silence"
  | "extract_channel"
  | "swap_channels"
  | "mono_mixdown"
  | "speed"
  | "split_channels";

const DURATION_CHANGING: OpType[] = ["trim", "delete", "remove_silence", "speed"];

export default function OperationPanel() {
  const asset = useEditorStore((s) => s.currentAsset());
  const selection = useEditorStore((s) => s.selection);
  const pushAsset = useEditorStore((s) => s.pushAsset);
  const setPendingOperation = useEditorStore((s) => s.setPendingOperation);
  const pendingOperation = useEditorStore((s) => s.pendingOperation);
  const setError = useEditorStore((s) => s.setError);
  const setWarning = useEditorStore((s) => s.setWarning);
  const isProcessing = useEditorStore((s) => s.isProcessing);
  const channelEdit = useEditorStore((s) => s.channelEdit);
  const updateChannelAsset = useEditorStore((s) => s.updateChannelAsset);
  const enterChannelEdit = useEditorStore((s) => s.enterChannelEdit);
  const enterFillerReview = useEditorStore((s) => s.enterFillerReview);
  const enterProfanityReview = useEditorStore((s) => s.enterProfanityReview);
  const enterNlePlanReview = useEditorStore((s) => s.enterNlePlanReview);
  const [detecting, setDetecting] = useState(false);
  const [detectingProfanity, setDetectingProfanity] = useState(false);
  const [censorshipSettingsOpen, setCensorshipSettingsOpen] = useState(false);
  const [nlePrompt, setNlePrompt] = useState("");
  const [planning, setPlanning] = useState(false);

  const [fadeDuration, setFadeDuration] = useState(1.0);
  const [fadeCurve, setFadeCurve] = useState<"linear" | "exponential">("linear");
  const [gainDb, setGainDb] = useState(0);
  const [targetDb, setTargetDb] = useState(-1);
  const [speedFactor, setSpeedFactor] = useState(1.0);
  const [silenceThreshold, setSilenceThreshold] = useState(-40);
  const [silenceMinDuration, setSilenceMinDuration] = useState(0.5);
  const [extractCh, setExtractCh] = useState<"left" | "right">("left");

  const abortRef = useRef<AbortController | null>(null);
  const resumedRef = useRef(false);

  // Abort any in-flight poll when the component unmounts.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // Resume a pending op that survived a refresh.
  useEffect(() => {
    if (!asset || !pendingOperation || resumedRef.current) return;
    if (pendingOperation.inputAssetId !== asset.assetId) return;
    resumedRef.current = true;

    const controller = new AbortController();
    abortRef.current = controller;

    (async () => {
      try {
        const completed = await pollOperation(pendingOperation.operationId, {
          signal: controller.signal,
        });
        applyCompletion(completed, pendingOperation.type as OpType);
      } catch (e) {
        if (e instanceof ApiRequestError && e.code === "ABORTED") return;
        setError(friendlyMessage(e));
      } finally {
        setPendingOperation(null);
        abortRef.current = null;
      }
    })();
  }, [asset, pendingOperation]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!asset) return null;

  const friendlyMessage = (e: unknown): string => {
    if (e instanceof ApiRequestError) {
      switch (e.code) {
        case "SERVER_RESTART":
          return "The previous operation was interrupted by a server restart. Please try again.";
        case "PROCESSING_TIMEOUT":
          return "Operation is taking longer than expected.";
        default:
          return e.message;
      }
    }
    return e instanceof Error ? e.message : "Operation failed";
  };

  const applyCompletion = (res: OperationResponse, type: OpType) => {
    if (!res.asset) return;
    if (type === "split_channels") {
      if (res.secondaryAsset) {
        enterChannelEdit(asset.assetId, res.asset, res.secondaryAsset);
      }
    } else if (channelEdit) {
      updateChannelAsset(channelEdit.activeChannel, res.asset);
    } else {
      pushAsset(res.asset, DURATION_CHANGING.includes(type));
    }
    if (res.warning) setWarning(res.warning);
  };

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

  const runOp = async (type: OpType, params: Record<string, unknown>) => {
    const validationError = validate(type, params);
    if (validationError) {
      setError(validationError);
      return;
    }
    if (pendingOperation) return; // single-op discipline

    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const enqueued = await enqueueOperation(type, asset.assetId, params);
      setPendingOperation({
        operationId: enqueued.operationId,
        type,
        inputAssetId: asset.assetId,
        startedAt: Date.now(),
      });
      const completed = await pollOperation(enqueued.operationId, {
        signal: controller.signal,
      });
      applyCompletion(completed, type);
    } catch (e: unknown) {
      if (e instanceof ApiRequestError && e.code === "ABORTED") return;
      setError(friendlyMessage(e));
    } finally {
      setPendingOperation(null);
      abortRef.current = null;
    }
  };

  const handleSplitChannels = () => runOp("split_channels", {});

  const handleFindFillers = async () => {
    if (!asset || detecting || isProcessing) return;

    const durationSec = asset.durationSec ?? 0;
    const confirmMsg =
      `Find filler words in this audio?\n\n` +
      `Duration: ${durationSec.toFixed(1)}s\n` +
      `The audio will be transcribed by the configured AI provider.`;
    if (!window.confirm(confirmMsg)) return;

    setError(null);
    setDetecting(true);
    try {
      const { operationId, result } = await detectFillers(asset.assetId, {
        confidence_threshold: 0,
      });
      enterFillerReview({
        operationId,
        inputAssetId: asset.assetId,
        result,
        rejectedWordIndices: new Set(),
        confidenceThreshold: 0.7,
      });
      if (result.regions.length === 0) {
        setWarning("No filler words detected in this audio.");
      }
    } catch (e) {
      setError(friendlyMessage(e));
    } finally {
      setDetecting(false);
    }
  };

  const handleAskAi = async () => {
    if (!asset || planning || isProcessing) return;
    const trimmed = nlePrompt.trim();
    if (!trimmed) {
      setError("Type a description of what you want the AI to do.");
      return;
    }
    setError(null);
    setPlanning(true);
    try {
      const { operationId, result } = await generateNlePlan(asset.assetId, {
        prompt: trimmed,
        // Pass the user's drag-selection as anchoring context. Backend stays
        // selection-aware via D5; if the user typed without selecting, no
        // selection block is sent.
        selection: selection
          ? { startSec: selection.startSec, endSec: selection.endSec }
          : null,
      });
      enterNlePlanReview({
        operationId,
        inputAssetId: asset.assetId,
        result,
        excludedStepIndices: new Set(),
        applyProgress: null,
      });
      // Don't auto-clear the prompt — the user may want to tweak + re-plan if
      // the LLM asked for clarification.
    } catch (e) {
      setError(friendlyMessage(e));
    } finally {
      setPlanning(false);
    }
  };

  const handleCensorProfanity = async () => {
    if (!asset || detectingProfanity || isProcessing) return;

    const durationSec = asset.durationSec ?? 0;
    const confirmMsg =
      `Find profanity in this audio?\n\n` +
      `Duration: ${durationSec.toFixed(1)}s\n` +
      `The audio will be transcribed by the configured AI provider; detected ` +
      `words will be replaced with a beep when you apply.`;
    if (!window.confirm(confirmMsg)) return;

    setError(null);
    setDetectingProfanity(true);
    try {
      const { operationId, result } = await detectProfanity(asset.assetId);
      enterProfanityReview({
        operationId,
        inputAssetId: asset.assetId,
        result,
        rejectedWordIndices: new Set(),
        // Per D4: slider hidden in Phase 1; threshold 0 keeps all matches visible.
        confidenceThreshold: 0,
        mode: "beep",
        beepHz: 1000,
      });
      if (result.regions.length === 0) {
        setWarning("No profanity detected in this audio.");
      }
    } catch (e) {
      setError(friendlyMessage(e));
    } finally {
      setDetectingProfanity(false);
    }
  };

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wide">Operations</h3>

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
          <select
            value={fadeCurve}
            onChange={(e) => setFadeCurve(e.target.value as "linear" | "exponential")}
            className="param-input"
          >
            <option value="linear">Linear</option>
            <option value="exponential">Exponential</option>
          </select>
        </div>
        <button
          disabled={isProcessing}
          onClick={() => runOp("fade_in", { duration_sec: fadeDuration, curve: fadeCurve })}
          className="op-btn"
        >
          Fade In
        </button>
        <button
          disabled={isProcessing}
          onClick={() => runOp("fade_out", { duration_sec: fadeDuration, curve: fadeCurve })}
          className="op-btn"
        >
          Fade Out
        </button>
      </div>

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

      {asset.channels === 2 && !channelEdit && (
        <>
          <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mt-4">Channel Operations</h4>
          <div className="flex flex-wrap items-end gap-2">
            <button disabled={isProcessing} onClick={handleSplitChannels} className="op-btn">
              Split &amp; Edit Channels
            </button>
            <div>
              <label className="text-xs text-slate-500">Channel</label>
              <select
                value={extractCh}
                onChange={(e) => setExtractCh(e.target.value as "left" | "right")}
                className="param-input"
              >
                <option value="left">Left</option>
                <option value="right">Right</option>
              </select>
            </div>
            <button
              disabled={isProcessing}
              onClick={() => runOp("extract_channel", { channel: extractCh })}
              className="op-btn"
            >
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

      <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mt-4">AI</h4>
      <div className="flex flex-wrap items-end gap-2">
        <button
          disabled={isProcessing || detecting}
          onClick={handleFindFillers}
          className="op-btn"
          title="Detect ums, uhs, and other filler words — review before removing"
        >
          {detecting ? "Transcribing…" : "Find filler words"}
        </button>
        <button
          disabled={isProcessing || detectingProfanity}
          onClick={handleCensorProfanity}
          className="op-btn"
          title="Detect profanity — review before censoring with a beep"
        >
          {detectingProfanity ? "Transcribing…" : "Censor profanity"}
        </button>
        <button
          onClick={() => setCensorshipSettingsOpen(true)}
          className="op-btn px-2"
          title="Edit censorship word list"
          aria-label="Edit censorship word list"
        >
          ⚙
        </button>
      </div>
      <CensorshipSettingsModal
        open={censorshipSettingsOpen}
        onClose={() => setCensorshipSettingsOpen(false)}
      />

      <div className="mt-4 space-y-2">
        <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
          Ask AI
        </h4>
        <p className="text-xs text-slate-500">
          Describe what you want in plain English. The AI proposes a plan you
          review before any audio changes.
          {selection && (
            <span className="block mt-1 text-blue-400">
              Your selection ({selection.startSec.toFixed(2)}s–
              {selection.endSec.toFixed(2)}s) will be passed along as context.
            </span>
          )}
        </p>
        <textarea
          value={nlePrompt}
          onChange={(e) => setNlePrompt(e.target.value)}
          disabled={planning || isProcessing}
          rows={2}
          placeholder='e.g. "Trim the first 30 seconds and fade out over 2 seconds"'
          className="w-full bg-slate-800 border border-slate-700 rounded p-2 text-sm text-slate-200 disabled:opacity-50 resize-y"
          onKeyDown={(e) => {
            // Cmd/Ctrl+Enter submits — common LLM-input convention.
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              void handleAskAi();
            }
          }}
        />
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-slate-600 italic">
            Your audio's spoken content is transcribed and sent to the configured
            LLM provider. Free-tier providers may use submitted data for training.
          </p>
          <button
            onClick={handleAskAi}
            disabled={planning || isProcessing || !nlePrompt.trim()}
            className="op-btn shrink-0"
            title="Generate a plan (Ctrl/Cmd+Enter)"
          >
            {planning ? "Planning…" : "Plan"}
          </button>
        </div>
      </div>

      {!selection && (
        <p className="text-xs text-slate-500 mt-2">Select a region on the waveform to use Trim and Delete</p>
      )}
    </div>
  );
}
