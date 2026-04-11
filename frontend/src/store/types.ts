export interface Asset {
  assetId: string;
  type: "original" | "derived";
  status: "processing" | "ready" | "failed";
  parentAssetId: string | null;
  audioUrl: string | null;
  waveformUrl: string | null;
  durationSec: number | null;
  sampleRate: number | null;
  channels: number | null;
}

export interface Selection {
  startSec: number;
  endSec: number;
}

export interface OperationResponse {
  operationId: string;
  status: string;
  warning: string | null;
  asset: Asset;
}

export interface ExportResponse {
  downloadUrl: string;
  format: string;
  sampleRate: number;
  channels: number;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: { field?: string; constraint?: string; received?: number | string };
  };
}
