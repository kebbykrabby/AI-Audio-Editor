import type { Asset } from "../store/types";
import { apiFetch, ApiRequestError } from "./client";

export async function uploadAudio(file: File): Promise<{ assetId: string; status: string }> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch("/api/assets/upload", { method: "POST", body: form });
}

export async function getAsset(id: string): Promise<Asset & { error?: { code: string; message: string } }> {
  return apiFetch(`/api/assets/${id}`);
}

export async function pollUntilReady(
  id: string,
  intervalMs = 2000,
  timeoutMs = 60000,
): Promise<Asset> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const asset = await getAsset(id);
    if (asset.status === "ready") return asset;
    if (asset.status === "failed") {
      // Surface the backend-provided error code/message instead of a generic string
      // so the UI can show meaningful feedback (e.g. INVALID_FILE vs PROCESSING_FAILED).
      const code = asset.error?.code ?? "PROCESSING_FAILED";
      const message = asset.error?.message ?? "Processing failed";
      throw new ApiRequestError(code, message);
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new ApiRequestError("PROCESSING_TIMEOUT", "Processing timed out after 60 seconds");
}
