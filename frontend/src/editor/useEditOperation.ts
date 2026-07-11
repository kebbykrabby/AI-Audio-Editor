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
        applyCompletion(completed, pendingOperation.type as OpType);
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

  const applyCompletion = (res: OperationResponse, type: OpType) => {
    if (!res.asset) return;
    if (type === "split_channels") {
      if (res.secondaryAsset && asset) {
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
      applyCompletion(completed, type);
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
