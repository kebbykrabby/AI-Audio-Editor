import { useEffect, useRef, useState } from "react";
import { getAsset } from "../api/assets";
import type { Asset } from "./types";
import { readPersistedAssetId, clearPersistedAssetId, useEditorStore } from "./editorStore";

const MAX_CHAIN_WALK = 200; // safety cap against cycles or pathological chains

/**
 * On mount, read the persisted currentAssetId and walk parentAssetId back to
 * the original so the frontend can reconstruct the edit chain across reloads.
 *
 * Redo-forward history is intentionally not restored (see PRD §Page Refresh).
 * Silently clears the stored id on any failure so the user lands on the upload
 * zone instead of an error banner.
 */
export function useRestoreSession(): { isRestoring: boolean } {
  const [isRestoring, setIsRestoring] = useState<boolean>(() => !!readPersistedAssetId());
  const hasRun = useRef(false);

  useEffect(() => {
    if (hasRun.current) return;
    hasRun.current = true;

    const storedId = readPersistedAssetId();
    if (!storedId) {
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
            // If the tip is still processing, just abandon restoration — user
            // probably reloaded mid-operation. Clear and show upload zone.
            clearPersistedAssetId();
            return;
          }
          chain.push(asset);
          nextId = asset.parentAssetId;
          steps += 1;
        }
        // chain is ordered [current, parent, grandparent, ..., root];
        // flip to chronological order for the history stack.
        const history = chain.reverse();
        useEditorStore.setState({
          assetHistory: history,
          currentIndex: history.length - 1,
          selection: null,
          error: null,
          warning: null,
        });
      } catch {
        // 404, network error, or any other failure — silently drop the stored id.
        clearPersistedAssetId();
      } finally {
        setIsRestoring(false);
      }
    })();
  }, []);

  return { isRestoring };
}
