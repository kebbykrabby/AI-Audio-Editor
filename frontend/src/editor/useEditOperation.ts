import { useEffect, useRef } from "react";

import { ApiRequestError } from "../api/client";
import { enqueueOperation, pollOperation } from "../api/operations";
import { useEditorStore } from "../store/editorStore";
import type { OperationResponse } from "../store/types";

export type OpType =
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

/**
 * Shared state machine that fronts every deterministic DSP operation:
 *   enqueue → persist pendingOperation → poll → apply → clear.
 *
 * Also resumes a pendingOperation left behind by a page refresh, and cleans up
 * any in-flight poll on unmount. Returns a single `runOp(type, params)` that
 * EditToolbar and AiActionsBar (and their equivalents) call.
 *
 * Preserving this contract is what lets the UI reskin swap markup freely
 * without touching the async pipeline that touches assets/operations.
 */
export function useEditOperation() {
  const asset = useEditorStore((s) => s.currentAsset());
  const pushAsset = useEditorStore((s) => s.pushAsset);
  const setPendingOperation = useEditorStore((s) => s.setPendingOperation);
  const pendingOperation = useEditorStore((s) => s.pendingOperation);
  const setError = useEditorStore((s) => s.setError);
  const setWarning = useEditorStore((s) => s.setWarning);
  const channelEdit = useEditorStore((s) => s.channelEdit);
  const updateChannelAsset = useEditorStore((s) => s.updateChannelAsset);
  const enterChannelEdit = useEditorStore((s) => s.enterChannelEdit);

  const abortRef = useRef<AbortController | null>(null);
  const resumedRef = useRef(false);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

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
        // We don't have the original params on a resumed op — use empty to
        // keep labels generic ("Trim", not "Trim to 0:15–1:30").
        applyCompletion(completed, pendingOperation.type as OpType, {});
      } catch (e) {
        if (e instanceof ApiRequestError && e.code === "ABORTED") return;
        setError(friendlyMessage(e));
      } finally {
        setPendingOperation(null);
        abortRef.current = null;
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asset, pendingOperation]);

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

  const applyCompletion = (
    res: OperationResponse,
    type: OpType,
    params: Record<string, unknown>,
  ) => {
    if (!res.asset) return;
    if (type === "split_channels") {
      if (res.secondaryAsset && asset) {
        enterChannelEdit(asset.assetId, res.asset, res.secondaryAsset);
      }
    } else if (channelEdit) {
      updateChannelAsset(channelEdit.activeChannel, res.asset);
    } else {
      pushAsset(res.asset, DURATION_CHANGING.includes(type), labelFor(type, params));
    }
    if (res.warning) setWarning(res.warning);
  };

  const validate = (type: OpType, params: Record<string, unknown>): string | null => {
    if (!asset) return "No audio loaded";
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
    if (!asset) return;
    const validationError = validate(type, params);
    if (validationError) {
      setError(validationError);
      return;
    }
    if (pendingOperation) return;

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
      applyCompletion(completed, type, params);
    } catch (e: unknown) {
      if (e instanceof ApiRequestError && e.code === "ABORTED") return;
      setError(friendlyMessage(e));
    } finally {
      setPendingOperation(null);
      abortRef.current = null;
    }
  };

  return { runOp };
}

/**
 * Turn a dispatched op + its params into a human-readable version label for
 * the History panel. Kept tight — the row width is small so the label needs
 * to fit in ~30 chars.
 */
function labelFor(type: OpType, params: Record<string, unknown>): string {
  const num = (k: string) => (typeof params[k] === "number" ? (params[k] as number) : null);
  const fmt = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  };
  switch (type) {
    case "trim": {
      const s = num("start_sec");
      const e = num("end_sec");
      return s != null && e != null ? `Trim ${fmt(s)}–${fmt(e)}` : "Trim";
    }
    case "delete": {
      const s = num("start_sec");
      const e = num("end_sec");
      return s != null && e != null ? `Delete ${fmt(s)}–${fmt(e)}` : "Delete";
    }
    case "fade_in": {
      const d = num("duration_sec");
      return d != null ? `Fade in (${d.toFixed(1)}s)` : "Fade in";
    }
    case "fade_out": {
      const d = num("duration_sec");
      return d != null ? `Fade out (${d.toFixed(1)}s)` : "Fade out";
    }
    case "gain": {
      const g = num("gain_db");
      return g != null ? `Gain ${g > 0 ? "+" : ""}${g} dB` : "Gain";
    }
    case "normalize": {
      const t = num("target_db");
      return t != null ? `Normalize to ${t} dB` : "Normalize";
    }
    case "reverse":
      return "Reverse";
    case "remove_silence":
      return "Remove silence";
    case "speed": {
      const f = num("factor");
      return f != null ? `Speed ${f.toFixed(2)}×` : "Speed";
    }
    case "mono_mixdown":
      return "Mono mixdown";
    case "swap_channels":
      return "Swap channels";
    case "extract_channel": {
      const ch = params.channel;
      return ch === "left"
        ? "Extract left"
        : ch === "right"
          ? "Extract right"
          : "Extract channel";
    }
    case "split_channels":
      return "Split channels";
  }
}
