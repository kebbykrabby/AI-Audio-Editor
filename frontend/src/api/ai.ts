import type {
  FillerDetectionResult,
  OperationResponse,
} from "../store/types";
import { apiFetch, ApiRequestError } from "./client";
import { pollOperation, type PollOptions } from "./operations";

export interface DetectFillersRequest {
  confidence_threshold?: number;
  categories?: string[] | null;
}

export async function enqueueDetectFillers(
  assetId: string,
  body: DetectFillersRequest = {},
): Promise<OperationResponse> {
  return apiFetch<OperationResponse>(
    `/api/assets/${assetId}/ai/detect-fillers`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

/**
 * Run the full detect flow: enqueue + poll + return the `FillerDetectionResult`.
 * Throws `ApiRequestError` on any step's failure.
 */
export async function detectFillers(
  assetId: string,
  body: DetectFillersRequest = {},
  opts: PollOptions = {},
): Promise<{ operationId: string; result: FillerDetectionResult }> {
  const enqueued = await enqueueDetectFillers(assetId, body);
  const completed = await pollOperation(enqueued.operationId, {
    // Transcription can be slow on CPU; give the default some headroom.
    timeoutMs: 300_000,
    ...opts,
  });
  if (!completed.result) {
    throw new ApiRequestError(
      "AI_OUTPUT_INVALID",
      "Detect completed without a result payload",
      0,
    );
  }
  return { operationId: completed.operationId, result: completed.result };
}
