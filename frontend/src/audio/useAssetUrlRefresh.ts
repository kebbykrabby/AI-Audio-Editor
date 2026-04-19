import { useEffect, useRef } from "react";
import { getAsset } from "../api/assets";
import { useEditorStore } from "../store/editorStore";

/**
 * Pre-emptively re-fetches an asset's signed URLs before they expire.
 *
 * Backend's SIGNED_URL_TTL_SEC is 600 (10 min); we refresh at 8 min, giving a
 * 2-min safety margin. LocalStorage proxy URLs don't expire, so refreshing is
 * a harmless no-op there.
 *
 * Exposes a manual trigger for media-error recovery: callers can invoke
 * `refreshNow()` from a WaveSurfer `error` handler.
 */
const DEFAULT_INTERVAL_MS = 8 * 60 * 1000;

export function useAssetUrlRefresh(
  assetId: string | null,
  intervalMs: number = DEFAULT_INTERVAL_MS,
): { refreshNow: () => Promise<void> } {
  const refreshAssetUrls = useEditorStore((s) => s.refreshAssetUrls);
  const inFlightRef = useRef(false);

  const doRefresh = async (id: string) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const fresh = await getAsset(id);
      refreshAssetUrls(id, fresh.audioUrl, fresh.waveformUrl);
    } catch {
      // refetch failed — silent, player will surface its own error on next load
    } finally {
      inFlightRef.current = false;
    }
  };

  useEffect(() => {
    if (!assetId) return;
    const timer = window.setInterval(() => void doRefresh(assetId), intervalMs);
    return () => window.clearInterval(timer);
    // doRefresh is stable-by-closure over refreshAssetUrls; we intentionally
    // don't list it as a dep to avoid resetting the timer on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId, intervalMs]);

  const refreshNow = async () => {
    if (assetId) await doRefresh(assetId);
  };

  return { refreshNow };
}
