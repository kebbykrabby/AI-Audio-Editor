import type { Asset } from "../store/types";
import { apiFetch } from "./client";

export async function uploadAudio(file: File): Promise<{ assetId: string; status: string }> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch("/api/assets/upload", { method: "POST", body: form });
}

export async function getAsset(id: string): Promise<Asset> {
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
      throw new Error("Processing failed");
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error("Processing timed out after 60 seconds");
}
