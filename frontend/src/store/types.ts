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

export interface FillerRegion {
  start: number;
  end: number;
  text: string;
  category: string;
  confidence: number;
  wordIndex: number;
}

export interface FillerDetectionResult {
  transcriptId: string;
  durationSec: number;
  language: string;
  regions: FillerRegion[];
  costUsd?: number | null;
  modelVersion: string;
}

export interface ProfanityRegion {
  start: number;
  end: number;
  text: string;
  wordIndex: number;
  confidence: number;
  category: string;
  matchedBy: string; // "exact" | "variants" | "phonetic"
}

export interface ProfanityDetectionResult {
  transcriptId: string;
  durationSec: number;
  language: string;
  regions: ProfanityRegion[];
  costUsd?: number | null;
  modelVersion: string;
}

// Phase 2 widens to: "beep" | "mute" | "cut" | "reverse_pitch"
export type CensorMode = "beep";

export interface OperationResponse {
  operationId: string;
  status: OperationStatus;
  warning?: string | null;
  asset?: Asset | null;
  secondaryAsset?: Asset | null;
  error?: ApiError["error"];
  // AI ops populate this; deterministic ops leave it absent. Shape varies by
  // op type — callers use the request's `type` (or the response context) to
  // know which interface to interpret it as.
  result?: FillerDetectionResult | ProfanityDetectionResult | null;
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
