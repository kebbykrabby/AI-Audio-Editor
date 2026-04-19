export interface User {
  userId: string;
  email: string | null;
  phoneNumber: string | null;
  displayName: string | null;
  emailVerified: boolean;
  phoneVerified: boolean;
}

export interface Asset {
  assetId: string;
  userId: string;
  type: "original" | "derived";
  status: "processing" | "ready" | "failed";
  parentAssetId: string | null;
  audioUrl: string | null;
  waveformUrl: string | null;
  durationSec: number | null;
  sampleRate: number | null;
  channels: number | null;
  filename: string | null;
  error?: ApiError["error"];
}

export interface Selection {
  startSec: number;
  endSec: number;
}

export type OperationStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface OperationResponse {
  operationId: string;
  status: OperationStatus;
  warning?: string | null;
  asset?: Asset | null;
  secondaryAsset?: Asset | null;
  error?: ApiError["error"];
}

export type ExportStatus = "queued" | "running" | "completed" | "failed";

export interface ExportResponse {
  exportId: string;
  status: ExportStatus;
  format: string;
  sampleRate?: number | null;
  bitrateKbps?: number | null;
  channels?: number | null;
  downloadUrl?: string | null;
  error?: ApiError["error"];
}

export interface TokenResponse {
  accessToken: string;
  expiresIn: number;
  user: User;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: { field?: string; constraint?: string; received?: number | string };
  };
}
