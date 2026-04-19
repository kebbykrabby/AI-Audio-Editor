import { useEffect, useRef, useState } from "react";
import { getAsset } from "../api/assets";
import type { Asset } from "./types";
import {
  clearPersistedAssetId,
  clearPersistedPendingOp,
  readPersistedAssetId,
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
