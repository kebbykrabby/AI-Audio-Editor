import type { ExportResponse } from "../store/types";
import { apiFetch } from "./client";

export async function exportAudio(
  assetId: string,
  format: "wav" | "mp3",
  sampleRate?: number,
  bitrateKbps?: number,
): Promise<ExportResponse> {
  return apiFetch(`/api/assets/${assetId}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      format,
      sample_rate: sampleRate,
      bitrate_kbps: bitrateKbps,
    }),
  });
}
