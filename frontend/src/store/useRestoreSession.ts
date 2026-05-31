import { useEffect, useRef, useState } from "react";
import { getAsset } from "../api/assets";
import { getOperation } from "../api/operations";
import type {
  Asset,
  FillerDetectionResult,
  NlePlanResult,
  ProfanityDetectionResult,
} from "./types";
import {
  clearPersistedAssetId,
  clearPersistedPendingOp,
  readPersistedAssetId,
  readPersistedLastDetectOperationId,
  readPersistedLastNlePlanOperationId,
  readPersistedLastProfanityOperationId,
  readPersistedPendingOp,
  useEditorStore,
} from "./editorStore";

const MAX_CHAIN_WALK = 200;

/**
 * On mount:
 *   1. Walk the persisted asset's parent chain to reconstruct the linear edit history.
 *   2. If a pending operation was persisted whose inputAssetId matches the restored
 *      tip, seed it into the store so OperationPanel can resume polling.
 *   3. Stale pending ops (different tip, asset unresolvable) are silently cleared.
 */
export function useRestoreSession(): { isRestoring: boolean } {
  const [isRestoring, setIsRestoring] = useState<boolean>(() => !!readPersistedAssetId());
  const hasRun = useRef(false);

  useEffect(() => {
    if (hasRun.current) return;
    hasRun.current = true;

    const storedId = readPersistedAssetId();
    const pending = readPersistedPendingOp();

    if (!storedId) {
      // No tip → any pending op is orphaned.
      if (pending) clearPersistedPendingOp();
      setIsRestoring(false);
      return;
    }

    (async () => {
      try {
        const chain: Asset[] = [];
        let nextId: string | null = storedId;
        let steps = 0;
        while (nextId && steps < MAX_CHAIN_WALK) {
          const asset = await getAsset(nextId);
          if (asset.status !== "ready") {
            clearPersistedAssetId();
            if (pending) clearPersistedPendingOp();
            return;
          }
          chain.push(asset);
          nextId = asset.parentAssetId;
          steps += 1;
        }
        const history = chain.reverse();
        const tip = history[history.length - 1] ?? null;

        useEditorStore.setState({
          assetHistory: history,
          currentIndex: history.length - 1,
          selection: null,
          error: null,
          warning: null,
        });

        if (pending && tip && pending.inputAssetId === tip.assetId) {
          useEditorStore.getState().setPendingOperation(pending);
        } else if (pending) {
          clearPersistedPendingOp();
        }

        // Restore an in-progress filler review: if the persisted op is still
        // completed AND its input asset is the current tip, re-enter review mode
        // without a second transcription.
        await restoreFillerReview(tip);
        await restoreProfanityReview(tip);
        await restoreNlePlanReview(tip);
      } catch {
        clearPersistedAssetId();
        clearPersistedPendingOp();
      } finally {
        setIsRestoring(false);
      }
    })();
  }, []);

  return { isRestoring };
}

async function restoreFillerReview(tip: Asset | null): Promise<void> {
  const lastDetectId = readPersistedLastDetectOperationId();
  if (!lastDetectId || !tip) return;
  try {
    const op = await getOperation(lastDetectId);
    if (op.status !== "completed" || !op.result) return;
    // Treat `op.result` as the FillerDetectionResult. The server never puts
    // anything else on an ai_detect_fillers op, and the backend has scoped
    // the fetch to the current user.
    const result = op.result as FillerDetectionResult;
    // Only restore if the detection was run on the current asset.
    if (result.durationSec !== tip.durationSec) return;
    useEditorStore.getState().enterFillerReview({
      operationId: lastDetectId,
      inputAssetId: tip.assetId,
      result,
      rejectedWordIndices: new Set(),
      confidenceThreshold: 0.7,
    });
  } catch {
    // Stale / deleted / cross-user → silently ignore.
  }
}

async function restoreProfanityReview(tip: Asset | null): Promise<void> {
  const lastId = readPersistedLastProfanityOperationId();
  if (!lastId || !tip) return;
  try {
    const op = await getOperation(lastId);
    if (op.status !== "completed" || !op.result) return;
    const result = op.result as ProfanityDetectionResult;
    if (result.durationSec !== tip.durationSec) return;
    useEditorStore.getState().enterProfanityReview({
      operationId: lastId,
      inputAssetId: tip.assetId,
      result,
      rejectedWordIndices: new Set(),
      // Per D4: slider is hidden while phonetic is off (Phase 1 always off).
      // Default keeps everything visible.
      confidenceThreshold: 0.0,
      mode: "beep",
      beepHz: 1000,
    });
  } catch {
    // Stale / deleted / cross-user → silently ignore.
  }
}

async function restoreNlePlanReview(tip: Asset | null): Promise<void> {
  const lastId = readPersistedLastNlePlanOperationId();
  if (!lastId || !tip) return;
  try {
    const op = await getOperation(lastId);
    if (op.status !== "completed" || !op.result) return;
    const result = op.result as NlePlanResult;
    // We don't have a duration on the plan result to gate against (NLE doesn't
    // produce a derived asset), so we trust that the persisted lastId belongs
    // to whatever asset was the tip when it was last persisted. If the user
    // navigated to a different asset since, the plan may not reference it
    // sensibly — that's OK, they can Cancel out.
    useEditorStore.getState().enterNlePlanReview({
      operationId: lastId,
      inputAssetId: tip.assetId,
      result,
      excludedStepIndices: new Set(),
      applyProgress: null,
    });
  } catch {
    // Stale / deleted / cross-user → silently ignore.
  }
}
