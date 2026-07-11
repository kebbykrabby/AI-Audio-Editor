import { create } from "zustand";
import type {
  Asset,
  CensorMode,
  FillerDetectionResult,
  NlePlanResult,
  ProfanityDetectionResult,
  Selection,
} from "./types";

const STORAGE_KEY = "audioEditor.currentAssetId";
const PENDING_OP_KEY = "audioEditor.pendingOperation";
const LAST_DETECT_OP_KEY = "audioEditor.lastDetectOperationId";
const LAST_PROFANITY_OP_KEY = "audioEditor.lastProfanityOperationId";
const LAST_NLE_PLAN_OP_KEY = "audioEditor.lastNlePlanOperationId";

function persistCurrentAssetId(id: string | null): void {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // localStorage unavailable (private mode, quota) — fail silently
  }
}

export function readPersistedAssetId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function clearPersistedAssetId(): void {
  persistCurrentAssetId(null);
}

export interface PendingOperation {
  operationId: string;
  type: string;
  inputAssetId: string;
  startedAt: number;
}

function persistPendingOp(op: PendingOperation | null): void {
  try {
    if (op) localStorage.setItem(PENDING_OP_KEY, JSON.stringify(op));
    else localStorage.removeItem(PENDING_OP_KEY);
  } catch {
    // fail silently
  }
}

export function readPersistedPendingOp(): PendingOperation | null {
  try {
    const raw = localStorage.getItem(PENDING_OP_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PendingOperation;
    if (!parsed.operationId || !parsed.inputAssetId || !parsed.type) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function clearPersistedPendingOp(): void {
  persistPendingOp(null);
}

function persistLastDetectOperationId(id: string | null): void {
  try {
    if (id) localStorage.setItem(LAST_DETECT_OP_KEY, id);
    else localStorage.removeItem(LAST_DETECT_OP_KEY);
  } catch {
    // fail silently
  }
}

export function readPersistedLastDetectOperationId(): string | null {
  try {
    return localStorage.getItem(LAST_DETECT_OP_KEY);
  } catch {
    return null;
  }
}

function persistLastProfanityOperationId(id: string | null): void {
  try {
    if (id) localStorage.setItem(LAST_PROFANITY_OP_KEY, id);
    else localStorage.removeItem(LAST_PROFANITY_OP_KEY);
  } catch {
    // fail silently
  }
}

export function readPersistedLastProfanityOperationId(): string | null {
  try {
    return localStorage.getItem(LAST_PROFANITY_OP_KEY);
  } catch {
    return null;
  }
}

function persistLastNlePlanOperationId(id: string | null): void {
  try {
    if (id) localStorage.setItem(LAST_NLE_PLAN_OP_KEY, id);
    else localStorage.removeItem(LAST_NLE_PLAN_OP_KEY);
  } catch {
    // fail silently
  }
}

export function readPersistedLastNlePlanOperationId(): string | null {
  try {
    return localStorage.getItem(LAST_NLE_PLAN_OP_KEY);
  } catch {
    return null;
  }
}

export interface ActiveFillerReview {
  operationId: string;
  inputAssetId: string;
  result: FillerDetectionResult;
  // Indices of regions the user has rejected. Initial state = empty = all accepted
  // above the confidence threshold.
  rejectedWordIndices: Set<number>;
  confidenceThreshold: number;
}

export interface ActiveProfanityReview {
  operationId: string;
  inputAssetId: string;
  result: ProfanityDetectionResult;
  rejectedWordIndices: Set<number>;
  confidenceThreshold: number;
  // Phase 2 widens this beyond "beep"; UI selector picks one mode per apply.
  mode: CensorMode;
  // Beep tone frequency. UI exposes a selector; default 1 kHz mirrors broadcast.
  beepHz: number;
}

export interface ActiveNlePlanReview {
  operationId: string;
  inputAssetId: string;
  result: NlePlanResult;
  // Step indices the user has toggled OFF. Initial state = empty = all
  // valid steps included. Invalid steps are always excluded regardless.
  excludedStepIndices: Set<number>;
  // Sequential apply progress (null when not applying).
  applyProgress: { currentIndex: number; totalEnabled: number } | null;
}

interface ChannelEditState {
  leftAsset: Asset;
  rightAsset: Asset;
  activeChannel: "left" | "right";
  originalAssetId: string;
}

interface EditorState {
  assetHistory: Asset[];
  /**
   * Parallel array to `assetHistory` — human-readable label per version, used
   * by the Version History panel. Populated at `pushAsset` time (session-
   * local; nothing persisted server-side). Restored sessions default each
   * entry to "Version N" until the user makes a new edit.
   */
  historyLabels: string[];
  currentIndex: number;
  isPlaying: boolean;
  currentTimeSec: number;
  selection: Selection | null;
  isUploading: boolean;
  isProcessing: boolean;
  pendingOperation: PendingOperation | null;
  error: string | null;
  warning: string | null;
  channelEdit: ChannelEditState | null;
  activeFillerReview: ActiveFillerReview | null;
  activeProfanityReview: ActiveProfanityReview | null;
  activeNlePlanReview: ActiveNlePlanReview | null;
  playbackRequest: { startSec: number; endSec: number; id: number } | null;

  currentAsset: () => Asset | null;
  canUndo: () => boolean;
  canRedo: () => boolean;

  setAssetReady: (asset: Asset) => void;
  pushAsset: (asset: Asset, durationChanged: boolean, label?: string) => void;
  /**
   * Jump to any index in the linear history. Clicking a row in the Version
   * History panel calls this. Same-index calls are a no-op.
   */
  jumpToHistory: (index: number) => void;
  refreshAssetUrls: (
    assetId: string,
    audioUrl: string | null,
    waveformUrl: string | null,
  ) => void;
  undo: () => void;
  redo: () => void;
  setSelection: (sel: Selection | null) => void;
  setPlaying: (playing: boolean) => void;
  setCurrentTime: (sec: number) => void;
  setUploading: (v: boolean) => void;
  setProcessing: (v: boolean) => void;
  setPendingOperation: (op: PendingOperation | null) => void;
  setError: (msg: string | null) => void;
  setWarning: (msg: string | null) => void;
  enterChannelEdit: (originalAssetId: string, left: Asset, right: Asset) => void;
  updateChannelAsset: (channel: "left" | "right", asset: Asset) => void;
  setActiveChannel: (ch: "left" | "right") => void;
  exitChannelEdit: () => void;
  enterFillerReview: (review: ActiveFillerReview) => void;
  toggleFillerReject: (wordIndex: number) => void;
  setFillerConfidenceThreshold: (threshold: number) => void;
  exitFillerReview: () => void;
  enterProfanityReview: (review: ActiveProfanityReview) => void;
  toggleProfanityReject: (wordIndex: number) => void;
  setProfanityConfidenceThreshold: (threshold: number) => void;
  setProfanityMode: (mode: CensorMode) => void;
  setProfanityBeepHz: (hz: number) => void;
  exitProfanityReview: () => void;
  enterNlePlanReview: (review: ActiveNlePlanReview) => void;
  toggleNlePlanStep: (stepIndex: number) => void;
  setNlePlanApplyProgress: (progress: { currentIndex: number; totalEnabled: number } | null) => void;
  exitNlePlanReview: () => void;
  playRange: (startSec: number, endSec: number) => void;
  reset: () => void;
}

const MAX_HISTORY = 100;

export const useEditorStore = create<EditorState>((set, get) => ({
  assetHistory: [],
  historyLabels: [],
  currentIndex: -1,
  isPlaying: false,
  currentTimeSec: 0,
  selection: null,
  isUploading: false,
  isProcessing: false,
  pendingOperation: null,
  error: null,
  warning: null,
  channelEdit: null,
  activeFillerReview: null,
  activeProfanityReview: null,
  activeNlePlanReview: null,
  playbackRequest: null,

  currentAsset: () => {
    const { channelEdit, assetHistory, currentIndex } = get();
    if (channelEdit) {
      return channelEdit.activeChannel === "left"
        ? channelEdit.leftAsset
        : channelEdit.rightAsset;
    }
    return currentIndex >= 0 ? assetHistory[currentIndex] : null;
  },

  canUndo: () => get().currentIndex > 0,
  canRedo: () => get().currentIndex < get().assetHistory.length - 1,

  setAssetReady: (asset) => {
    set({
      assetHistory: [asset],
      historyLabels: [asset.filename || "Original upload"],
      currentIndex: 0,
      error: null,
      warning: null,
    });
    persistCurrentAssetId(asset.assetId);
  },

  pushAsset: (asset, durationChanged, label) => {
    const { assetHistory, historyLabels, currentIndex } = get();
    let newHistory = assetHistory.slice(0, currentIndex + 1);
    let newLabels = historyLabels.slice(0, currentIndex + 1);
    newHistory.push(asset);
    newLabels.push(label ?? "Edit");
    let newIndex = newHistory.length - 1;
    if (newHistory.length > MAX_HISTORY) {
      const overflow = newHistory.length - MAX_HISTORY;
      newHistory = newHistory.slice(overflow);
      newLabels = newLabels.slice(overflow);
      newIndex -= overflow;
    }
    set({
      assetHistory: newHistory,
      historyLabels: newLabels,
      currentIndex: newIndex,
      selection: durationChanged ? null : get().selection,
      warning: null,
    });
    persistCurrentAssetId(asset.assetId);
  },

  jumpToHistory: (index) => {
    const { assetHistory, currentIndex } = get();
    if (index === currentIndex) return;
    if (index < 0 || index >= assetHistory.length) return;
    set({ currentIndex: index, selection: null, warning: null });
    persistCurrentAssetId(assetHistory[index].assetId);
  },

  refreshAssetUrls: (assetId, audioUrl, waveformUrl) => {
    const { assetHistory, channelEdit } = get();
    const patch = (a: Asset): Asset =>
      a.assetId === assetId ? { ...a, audioUrl, waveformUrl } : a;

    const nextHistory = assetHistory.map(patch);
    const nextChannelEdit = channelEdit
      ? {
          ...channelEdit,
          leftAsset: patch(channelEdit.leftAsset),
          rightAsset: patch(channelEdit.rightAsset),
        }
      : null;
    set({ assetHistory: nextHistory, channelEdit: nextChannelEdit });
  },

  undo: () => {
    const { currentIndex, assetHistory } = get();
    if (currentIndex > 0) {
      const newIndex = currentIndex - 1;
      set({ currentIndex: newIndex, selection: null, warning: null });
      persistCurrentAssetId(assetHistory[newIndex].assetId);
    }
  },

  redo: () => {
    const { currentIndex, assetHistory } = get();
    if (currentIndex < assetHistory.length - 1) {
      const newIndex = currentIndex + 1;
      set({ currentIndex: newIndex, selection: null, warning: null });
      persistCurrentAssetId(assetHistory[newIndex].assetId);
    }
  },

  setSelection: (sel) => set({ selection: sel }),
  setPlaying: (playing) => set({ isPlaying: playing }),
  setCurrentTime: (sec) => set({ currentTimeSec: sec }),
  setUploading: (v) => set({ isUploading: v }),
  setProcessing: (v) => set({ isProcessing: v }),

  setPendingOperation: (op) => {
    persistPendingOp(op);
    set({ pendingOperation: op, isProcessing: op !== null });
  },

  setError: (msg) => set({ error: msg }),
  setWarning: (msg) => set({ warning: msg }),

  enterChannelEdit: (originalAssetId, left, right) => {
    set({
      channelEdit: { leftAsset: left, rightAsset: right, activeChannel: "left", originalAssetId },
      selection: null,
      warning: null,
    });
  },

  updateChannelAsset: (channel, asset) => {
    const ce = get().channelEdit;
    if (!ce) return;
    set({
      channelEdit: {
        ...ce,
        leftAsset: channel === "left" ? asset : ce.leftAsset,
        rightAsset: channel === "right" ? asset : ce.rightAsset,
      },
    });
  },

  setActiveChannel: (ch) => {
    const ce = get().channelEdit;
    if (!ce) return;
    set({ channelEdit: { ...ce, activeChannel: ch }, selection: null });
  },

  exitChannelEdit: () => set({ channelEdit: null, selection: null }),

  enterFillerReview: (review) => {
    persistLastDetectOperationId(review.operationId);
    set({ activeFillerReview: review });
  },

  toggleFillerReject: (wordIndex) => {
    const review = get().activeFillerReview;
    if (!review) return;
    const next = new Set(review.rejectedWordIndices);
    if (next.has(wordIndex)) next.delete(wordIndex);
    else next.add(wordIndex);
    set({ activeFillerReview: { ...review, rejectedWordIndices: next } });
  },

  setFillerConfidenceThreshold: (threshold) => {
    const review = get().activeFillerReview;
    if (!review) return;
    set({
      activeFillerReview: {
        ...review,
        confidenceThreshold: Math.max(0, Math.min(1, threshold)),
      },
    });
  },

  exitFillerReview: () => {
    persistLastDetectOperationId(null);
    set({ activeFillerReview: null });
  },

  enterProfanityReview: (review) => {
    persistLastProfanityOperationId(review.operationId);
    set({ activeProfanityReview: review });
  },

  toggleProfanityReject: (wordIndex) => {
    const review = get().activeProfanityReview;
    if (!review) return;
    const next = new Set(review.rejectedWordIndices);
    if (next.has(wordIndex)) next.delete(wordIndex);
    else next.add(wordIndex);
    set({ activeProfanityReview: { ...review, rejectedWordIndices: next } });
  },

  setProfanityConfidenceThreshold: (threshold) => {
    const review = get().activeProfanityReview;
    if (!review) return;
    set({
      activeProfanityReview: {
        ...review,
        confidenceThreshold: Math.max(0, Math.min(1, threshold)),
      },
    });
  },

  setProfanityMode: (mode) => {
    const review = get().activeProfanityReview;
    if (!review) return;
    set({ activeProfanityReview: { ...review, mode } });
  },

  setProfanityBeepHz: (hz) => {
    const review = get().activeProfanityReview;
    if (!review) return;
    set({
      activeProfanityReview: {
        ...review,
        beepHz: Math.max(200, Math.min(8000, Math.round(hz))),
      },
    });
  },

  exitProfanityReview: () => {
    persistLastProfanityOperationId(null);
    set({ activeProfanityReview: null });
  },

  enterNlePlanReview: (review) => {
    persistLastNlePlanOperationId(review.operationId);
    set({ activeNlePlanReview: review });
  },

  toggleNlePlanStep: (stepIndex) => {
    const review = get().activeNlePlanReview;
    if (!review) return;
    const next = new Set(review.excludedStepIndices);
    if (next.has(stepIndex)) next.delete(stepIndex);
    else next.add(stepIndex);
    set({ activeNlePlanReview: { ...review, excludedStepIndices: next } });
  },

  setNlePlanApplyProgress: (progress) => {
    const review = get().activeNlePlanReview;
    if (!review) return;
    set({ activeNlePlanReview: { ...review, applyProgress: progress } });
  },

  exitNlePlanReview: () => {
    persistLastNlePlanOperationId(null);
    set({ activeNlePlanReview: null });
  },

  playRange: (startSec, endSec) =>
    set({ playbackRequest: { startSec, endSec, id: Date.now() } }),

  reset: () => {
    set({
      assetHistory: [],
      historyLabels: [],
      currentIndex: -1,
      isPlaying: false,
      currentTimeSec: 0,
      selection: null,
      isUploading: false,
      isProcessing: false,
      pendingOperation: null,
      error: null,
      warning: null,
      channelEdit: null,
      activeFillerReview: null,
      activeProfanityReview: null,
      activeNlePlanReview: null,
      playbackRequest: null,
    });
    clearPersistedAssetId();
    clearPersistedPendingOp();
    persistLastDetectOperationId(null);
    persistLastProfanityOperationId(null);
    persistLastNlePlanOperationId(null);
  },
}));
