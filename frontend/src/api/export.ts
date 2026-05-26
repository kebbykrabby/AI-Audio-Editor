import type { ExportResponse } from "../store/types";
import { apiFetch, ApiRequestError } from "./client";
import type { PollOptions } from "./operations";

export async function enqueueExport(
  assetId: string,
  format: "wav" | "mp3",
  sampleRate?: number,
  bitrateKbps?: number,
): Promise<ExportResponse> {
  return apiFetch<ExportResponse>(`/api/assets/${assetId}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      format,
      sample_rate: sampleRate,
      bitrate_kbps: bitrateKbps,
    }),
  });
}

export async function getExport(exportId: string): Promise<ExportResponse> {
  return apiFetch<ExportResponse>(`/api/exports/${exportId}`);
}

export async function pollExport(
  exportId: string,
  opts: PollOptions = {},
): Promise<ExportResponse> {
  const { intervalMs = 2000, timeoutMs = 300_000, signal } = opts;
  const start = Date.now();

  while (Date.now() - start < timeoutMs) {
    if (signal?.aborted) {
      throw new ApiRequestError("ABORTED", "Polling aborted", 0);
    }
    const res = await getExport(exportId);
    if (res.status === "completed") {
      if (!res.downloadUrl) {
        throw new ApiRequestError("EXPORT_FAILED", "Export completed without a download URL", 0);
      }
      return res;
    }
    if (res.status === "failed") {
      const code = res.error?.code || "EXPORT_FAILED";
      const message = res.error?.message || "Export failed";
      throw new ApiRequestError(code, message, 0, res.error?.details);
    }
    await sleep(intervalMs, signal);
  }

  throw new ApiRequestError("PROCESSING_TIMEOUT", "Export polling timed out", 0);
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new ApiRequestError("ABORTED", "Polling aborted", 0));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new ApiRequestError("ABORTED", "Polling aborted", 0));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
