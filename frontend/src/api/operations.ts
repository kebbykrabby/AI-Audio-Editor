import type { OperationResponse } from "../store/types";
import { apiFetch, ApiRequestError } from "./client";

export interface PollOptions {
  intervalMs?: number;
  timeoutMs?: number;
  signal?: AbortSignal;
}

export async function enqueueOperation(
  type: string,
  inputAssetId: string,
  parameters: Record<string, unknown>,
): Promise<OperationResponse> {
  return apiFetch<OperationResponse>(`/api/assets/${inputAssetId}/operations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, parameters }),
  });
}

export async function getOperation(operationId: string): Promise<OperationResponse> {
  return apiFetch<OperationResponse>(`/api/operations/${operationId}`);
}

export async function pollOperation(
  operationId: string,
  opts: PollOptions = {},
): Promise<OperationResponse> {
  const { intervalMs = 2000, timeoutMs = 300_000, signal } = opts;
  const start = Date.now();

  while (Date.now() - start < timeoutMs) {
    if (signal?.aborted) {
      throw new ApiRequestError("ABORTED", "Polling aborted", 0);
    }
    const res = await getOperation(operationId);
    if (res.status === "completed") return res;
    if (res.status === "failed" || res.status === "cancelled") {
      const code = res.error?.code || "PROCESSING_FAILED";
      const message = res.error?.message || "Operation failed";
      throw new ApiRequestError(code, message, 0, res.error?.details);
    }
    await sleep(intervalMs, signal);
  }

  throw new ApiRequestError("PROCESSING_TIMEOUT", "Operation polling timed out", 0);
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
