import type { OperationResponse } from "../store/types";
import { apiFetch } from "./client";

export async function executeOperation(
  type: string,
  inputAssetId: string,
  parameters: Record<string, unknown>,
): Promise<OperationResponse> {
  return apiFetch(`/api/assets/${inputAssetId}/operations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      type,
      parameters,
    }),
  });
}
