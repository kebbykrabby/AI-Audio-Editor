import type {
  NlePlanResult,
  NleSelection,
  OperationResponse,
} from "../store/types";
import { apiFetch, ApiRequestError } from "./client";
import { pollOperation, type PollOptions } from "./operations";

export interface GenerateNlePlanRequest {
  prompt: string;
  selection?: NleSelection | null;
}

export async function enqueueGenerateNlePlan(
  assetId: string,
  body: GenerateNlePlanRequest,
): Promise<OperationResponse> {
  return apiFetch<OperationResponse>(
    `/api/assets/${assetId}/ai/plan`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: body.prompt,
        // Only include selection when actually set, so the server can
        // distinguish "no selection" from "selection with zero width".
        ...(body.selection ? { selection: body.selection } : {}),
      }),
    },
  );
}

/**
 * Enqueue + poll + return the completed `NlePlanResult`.
 * Throws `ApiRequestError` on any step's failure.
 */
export async function generateNlePlan(
  assetId: string,
  body: GenerateNlePlanRequest,
  opts: PollOptions = {},
): Promise<{ operationId: string; result: NlePlanResult }> {
  const enqueued = await enqueueGenerateNlePlan(assetId, body);
  const completed = await pollOperation(enqueued.operationId, {
    // LLM round trip plus transcription on first call; same cushion as detect.
    timeoutMs: 300_000,
    ...opts,
  });
  if (!completed.result) {
    throw new ApiRequestError(
      "AI_OUTPUT_INVALID",
      "Plan generation completed without a result payload",
      0,
    );
  }
  return {
    operationId: completed.operationId,
    result: completed.result as NlePlanResult,
  };
}
